from fastapi import APIRouter, File, HTTPException, UploadFile
from app.services.geospatial import process_upload
from app.services.storage import FILE_STORE

router = APIRouter(tags=["Geospatial files"])
ALLOWED_EXTENSIONS = {".kml", ".zip"}
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


@router.post("/files/", status_code=201)
async def upload_file(file: UploadFile = File(...)):
    filename = file.filename or "upload"
    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Upload a .kml file or a .zip containing a Shapefile.")
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File is too large. Maximum upload size is 25 MB.")
    if not content:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    try:
        record = process_upload(filename, content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        # Avoid exposing internal server details to API clients.
        raise HTTPException(status_code=422, detail="Could not process this geospatial file. Check its contents and CRS.") from exc
    FILE_STORE[record["id"]] = record
    return {
        "id": record["id"],
        "filename": record["filename"],
        "feature_count": record["feature_count"],
        "crs": record["crs"],
        "measurement_crs": record["measurement_crs"],
        "status": record["status"],
    }


@router.get("/files/{file_id}/")
def get_file(file_id: str):
    record = FILE_STORE.get(file_id)
    if record is None:
        raise HTTPException(status_code=404, detail="File ID not found. Upload the file again.")
    return {
        "id": record["id"],
        "filename": record["filename"],
        "feature_count": record["feature_count"],
        "crs": record["crs"],
        "measurement_crs": record["measurement_crs"],
        "status": record["status"],
        "features": record["features"],
    }


@router.get("/files/{file_id}/measurements/")
def get_measurements(file_id: str):
    record = FILE_STORE.get(file_id)
    if record is None:
        raise HTTPException(status_code=404, detail="File ID not found. Upload the file again.")
    return {
        "id": record["id"],
        "filename": record["filename"],
        "crs": record["crs"],
        "measurement_crs": record["measurement_crs"],
        "measurements": record["measurements"],
    }
