import io
import json
import math
import os
import uuid
import zipfile
import xml.etree.ElementTree as ET

import shapefile
from pyproj import CRS, Transformer
from shapely.geometry import Point, LineString, Polygon, shape, mapping
from shapely.ops import transform

KML_NS = {"kml": "http://www.opengis.net/kml/2.2"}
MAX_ZIP_MEMBERS = 2000
MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024


def _coordinates(text):
    coords = []
    for item in (text or "").strip().split():
        parts = item.split(",")
        if len(parts) >= 2:
            coords.append((float(parts[0]), float(parts[1])))
    return coords


def _parse_kml_geometry(element):
    tag = element.tag.rsplit("}", 1)[-1]
    if tag == "Point":
        coords = _coordinates(element.findtext("kml:coordinates", default="", namespaces=KML_NS))
        return Point(coords[0]) if coords else None
    if tag == "LineString":
        coords = _coordinates(element.findtext("kml:coordinates", default="", namespaces=KML_NS))
        return LineString(coords) if len(coords) >= 2 else None
    if tag == "Polygon":
        outer = element.find(".//kml:outerBoundaryIs/kml:LinearRing/kml:coordinates", KML_NS)
        if outer is None:
            return None
        shell = _coordinates(outer.text)
        holes = []
        for inner in element.findall(".//kml:innerBoundaryIs/kml:LinearRing/kml:coordinates", KML_NS):
            ring = _coordinates(inner.text)
            if len(ring) >= 4:
                holes.append(ring)
        return Polygon(shell, holes) if len(shell) >= 4 else None
    if tag == "MultiGeometry":
        geoms = [g for child in element for g in [_parse_kml_geometry(child)] if g is not None]
        if not geoms:
            return None
        from shapely.geometry import GeometryCollection
        return GeometryCollection(geoms)
    return None


def _read_kml(content):
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise ValueError("The KML file is not valid XML.") from exc
    features = []
    for placemark in root.findall(".//kml:Placemark", KML_NS):
        geom = None
        for child in placemark:
            if child.tag.rsplit("}", 1)[-1] in {"Point", "LineString", "Polygon", "MultiGeometry"}:
                geom = _parse_kml_geometry(child)
                if geom is not None:
                    break
        if geom is None:
            continue
        props = {}
        name = placemark.findtext("kml:name", default=None, namespaces=KML_NS)
        if name is not None:
            props["name"] = name
        description = placemark.findtext("kml:description", default=None, namespaces=KML_NS)
        if description is not None:
            props["description"] = description
        for data in placemark.findall(".//kml:ExtendedData/kml:Data", KML_NS):
            key = data.attrib.get("name")
            value = data.findtext("kml:value", default="", namespaces=KML_NS)
            if key:
                props[key] = value
        features.append((geom, props))
    if not features:
        raise ValueError("No supported Point, LineString, or Polygon placemarks were found in the KML.")
    return features, CRS.from_epsg(4326)


def _read_shapefile_zip(content):
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise ValueError("The uploaded ZIP file is invalid.") from exc
    with archive:
        members = [m for m in archive.infolist() if not m.is_dir()]
        if len(members) > MAX_ZIP_MEMBERS:
            raise ValueError("ZIP contains too many files.")
        if sum(m.file_size for m in members) > MAX_UNCOMPRESSED_BYTES:
            raise ValueError("Uncompressed ZIP content exceeds 100 MB.")
        # Read files directly from the archive; never extract untrusted paths.
        by_lower = {m.filename.replace("\\", "/").lower(): m for m in members}
        shp_paths = [m.filename for m in members if m.filename.lower().endswith(".shp")]
        if not shp_paths:
            raise ValueError("ZIP must contain a .shp file and its associated .shx/.dbf files.")
        shp_path = shp_paths[0]
        base = shp_path[:-4]
        def read_sidecar(ext):
            target = (base + ext).lower()
            for name, member in by_lower.items():
                if name == target or name.endswith("/" + target.split("/")[-1]):
                    return archive.read(member)
            return None
        shp = archive.read(shp_path)
        shx = read_sidecar(".shx")
        dbf = read_sidecar(".dbf")
        prj = read_sidecar(".prj")
        if shx is None or dbf is None:
            raise ValueError("Shapefile ZIP must include matching .shp, .shx, and .dbf files.")
        if prj is None:
            raise ValueError("Shapefile ZIP must include a .prj file so measurements use the correct CRS.")
        try:
            source_crs = CRS.from_wkt(prj.decode("utf-8", errors="ignore"))
        except Exception as exc:
            raise ValueError("Could not read the Shapefile .prj coordinate reference system.") from exc
        reader = shapefile.Reader(shp=io.BytesIO(shp), shx=io.BytesIO(shx), dbf=io.BytesIO(dbf), encoding="utf-8")
        fields = [f[0] for f in reader.fields[1:]]
        features = []
        for sr in reader.iterShapeRecords():
            geom = shape(sr.shape.__geo_interface__)
            props = dict(zip(fields, list(sr.record)))
            features.append((geom, props))
        if not features:
            raise ValueError("The Shapefile contains no features.")
        return features, source_crs


def _safe_json(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return value
    return str(value)


def _choose_measurement_crs(source_crs, features):
    if source_crs.is_projected:
        return source_crs
    # Select a UTM zone based on the mean of available feature centroids.
    xs, ys = [], []
    for geom, _ in features:
        if not geom.is_empty:
            c = geom.centroid
            xs.append(c.x)
            ys.append(c.y)
    if not xs:
        raise ValueError("The file contains no non-empty geometries to measure.")
    lon = sum(xs) / len(xs)
    lat = max(-80.0, min(84.0, sum(ys) / len(ys)))
    zone = max(1, min(60, int((lon + 180) // 6) + 1))
    epsg = (32600 if lat >= 0 else 32700) + zone
    return CRS.from_epsg(epsg)


def process_upload(filename, content):
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".kml":
        features, source_crs = _read_kml(content)
    elif ext == ".zip":
        features, source_crs = _read_shapefile_zip(content)
    else:
        raise ValueError("Unsupported file type. Upload .kml or .zip.")
    if not features:
        raise ValueError("No features were found in the uploaded file.")

    measurement_crs = _choose_measurement_crs(source_crs, features)
    transformer = Transformer.from_crs(source_crs, measurement_crs, always_xy=True)
    output_features, measurements = [], []
    for index, (geom, properties) in enumerate(features):
        geometry_type = geom.geom_type
        feature_item = {
            "feature_id": index,
            "geometry_type": geometry_type,
            "geometry": mapping(geom),
            "crs": source_crs.to_string(),
            "properties": {str(k): _safe_json(v) for k, v in properties.items()},
        }
        output_features.append(feature_item)
        result = {"feature_id": index, "geometry_type": geometry_type, "status": "COMPLETED"}
        if geom.is_empty:
            result.update({"status": "SKIPPED", "reason": "Empty geometry"})
        elif geometry_type in {"Polygon", "MultiPolygon"}:
            projected = transform(transformer.transform, geom)
            result["area"] = float(projected.area)
            result["area_unit"] = "square metres" if measurement_crs.axis_info[0].unit_name.lower() in {"metre", "meter"} else measurement_crs.axis_info[0].unit_name + " squared"
        elif geometry_type in {"LineString", "MultiLineString", "LinearRing"}:
            projected = transform(transformer.transform, geom)
            result["length"] = float(projected.length)
            result["length_unit"] = "metres" if measurement_crs.axis_info[0].unit_name.lower() in {"metre", "meter"} else measurement_crs.axis_info[0].unit_name
        elif geometry_type in {"Point", "MultiPoint"}:
            result["status"] = "NO_MEASUREMENT_REQUIRED"
        else:
            result["status"] = "UNSUPPORTED_GEOMETRY"
            result["reason"] = "Measurement is not implemented for this geometry type."
        measurements.append(result)

    return {
        "id": str(uuid.uuid4()),
        "filename": os.path.basename(filename),
        "feature_count": len(output_features),
        "crs": source_crs.to_string(),
        "measurement_crs": measurement_crs.to_string(),
        "status": "COMPLETED",
        "features": output_features,
        "measurements": measurements,
    }
