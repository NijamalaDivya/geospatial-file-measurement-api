from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_root():
    response = client.get("/")
    assert response.status_code == 200
    assert "running" in response.json()["message"]


def test_rejects_unsupported_extension():
    response = client.post(
        "/api/files/",
        files={"file": ("notes.txt", b"not geospatial", "text/plain")},
    )
    assert response.status_code == 400


def test_file_not_found():
    response = client.get("/api/files/not-a-real-id/")
    assert response.status_code == 404


def test_upload_kml_and_measurements():
    kml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <kml xmlns="http://www.opengis.net/kml/2.2"><Document>
      <Placemark><name>triangle</name><Polygon><outerBoundaryIs><LinearRing>
      <coordinates>77.0,13.0 77.001,13.0 77.001,13.001 77.0,13.0</coordinates>
      </LinearRing></outerBoundaryIs></Polygon></Placemark>
      <Placemark><name>road</name><LineString>
      <coordinates>77.0,13.0 77.001,13.001</coordinates>
      </LineString></Placemark>
      <Placemark><name>point</name><Point><coordinates>77.0,13.0</coordinates></Point></Placemark>
    </Document></kml>"""
    response = client.post(
        "/api/files/",
        files={"file": ("survey.kml", kml, "application/vnd.google-earth.kml+xml")},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["feature_count"] == 3
    assert body["crs"] == "EPSG:4326"
    assert body["measurement_crs"].startswith("EPSG:326")
    file_id = body["id"]

    detail = client.get(f"/api/files/{file_id}/")
    assert detail.status_code == 200
    assert len(detail.json()["features"]) == 3

    measurements = client.get(f"/api/files/{file_id}/measurements/")
    assert measurements.status_code == 200
    items = measurements.json()["measurements"]
    assert items[0]["area"] > 0
    assert items[1]["length"] > 0
    assert items[2]["status"] == "NO_MEASUREMENT_REQUIRED"
