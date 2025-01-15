from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, HttpUrl
from services.extractor import AudioExtractor
import logging
from urllib.parse import quote
import os
import zipfile
from fastapi import BackgroundTasks
from mutagen.id3 import ID3

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/extract-video")
async def extract_video():
    return {"status": "called extract-video"}




