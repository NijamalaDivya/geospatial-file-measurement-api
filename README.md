# Geospatial File Measurement API

FastAPI backend that accepts KML files or ZIP archives containing Shapefiles, extracts feature geometry and properties, and calculates polygon area and line length using a projected coordinate reference system (CRS).

## Features
- `POST /api/files/` uploads and processes `.kml` or `.zip` Shapefiles.
- `GET /api/files/{id}/` returns file information and feature details.
- `GET /api/files/{id}/measurements/` returns per-feature measurements.
- KML is interpreted as WGS 84 / EPSG:4326.
- Shapefiles require a `.prj` file so measurements can use the correct CRS.
- Geographic coordinates are projected to a UTM CRS before measuring.
- Point features are returned without a measurement; unsupported geometry types are reported instead of crashing.
- Basic upload and ZIP size limits are enforced.

## Project structure
```text
app/
  main.py
  routes/
    __init__.py
    files.py
  services/
    __init__.py
    geospatial.py
    storage.py
requirements.txt
render.yaml
runtime.txt
README.md
tests/
```

## Run locally
Python 3.11 or 3.12 is recommended.

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/docs` for interactive API documentation.

## API usage

### Upload
Use `POST /api/files/` as `multipart/form-data`, with the file field named `file`. Upload either a `.kml` file or a `.zip` containing `.shp`, `.shx`, `.dbf`, and `.prj` files.

Example response:
```json
{
  "id": "generated-uuid",
  "filename": "survey.kml",
  "feature_count": 3,
  "crs": "EPSG:4326",
  "measurement_crs": "EPSG:32643",
  "status": "COMPLETED"
}
```

### File details
`GET /api/files/{id}/` returns file metadata and feature details including feature index, geometry type, GeoJSON-style geometry, CRS, and attributes.

### Measurements
`GET /api/files/{id}/measurements/` returns the measurements for each feature. Polygon area is in square metres when the selected CRS uses metres. Line length is in metres when the selected CRS uses metres. Points require no measurement.

**Important:** IDs are stored in memory for this demo. Upload a file again if the service restarts or the Render instance sleeps/restarts. For durable production storage, use a database and object storage.

## Render deployment
1. Push the full project folder to a public GitHub repository.
2. In Render, create a **New Web Service** and connect that repository.
3. Set **Root Directory** to the repository root (leave blank if the app is at the root).
4. Build command: `pip install -r requirements.txt`
5. Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
6. Deploy, then open `https://YOUR-RENDER-SERVICE.onrender.com/docs`.
7. Test `POST /api/files/` by uploading a real KML or zipped Shapefile.

The included `render.yaml` has the same build and start commands. Do not deploy only the `app` directory; deploy the whole repository so Render can install dependencies.

## Measurement and CRS decisions
- KML coordinates are defined as longitude/latitude in EPSG:4326.
- For geographic source CRS data, a UTM zone is selected from the feature centroid and the geometry is transformed before area/length calculations.
- A projected source CRS is used as supplied. If its units are not metres, the API reports the CRS unit name.
- Shapefile archives are read directly from ZIP memory rather than extracting untrusted archive paths.

## Learning and future scope
This project demonstrates API design, file validation, geospatial formats, coordinate transformations, geometry processing, and deployment.
Possible improvements: persistent database/object storage, background processing for large files, authentication, richer CRS selection for datasets spanning multiple UTM zones, structured logging, and more automated tests.
