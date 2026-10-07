"""Bounded untrusted-file reads, metadata-free images and private error messages."""
import json
import os
import re
import tempfile
from pathlib import Path
from PIL import Image

MAX_IMAGE_PIXELS=25_000_000
MAX_IMAGE_BYTES=50_000_000

class ValidationError(ValueError):
    """An application-written explanation safe to show without exception data."""

def plain_text(value,limit):
    if not isinstance(value,str) or len(value)>limit or re.search(r'[\x00-\x1f\x7f]',value):
        raise ValidationError('Invalid text field. Use plain text within the supported length.')
    return value

def _pairs(pairs):
    data={}
    for key,value in pairs:
        if key in data:raise ValidationError('Duplicate JSON keys are not supported.')
        data[key]=value
    return data

def parse_json(text):
    try:
        data=json.loads(text,object_pairs_hook=_pairs,parse_constant=lambda value:(_ for _ in ()).throw(ValidationError('Non-finite JSON values are not supported.')))
        stack=[(data,0)]
        while stack:
            item,depth=stack.pop()
            if depth>64:raise ValidationError('File structure is too complex.')
            if isinstance(item,dict):stack.extend((value,depth+1) for value in item.values() if isinstance(value,(dict,list)))
            elif isinstance(item,list):stack.extend((value,depth+1) for value in item if isinstance(value,(dict,list)))
        return data
    except (RecursionError,OverflowError) as exc:raise ValidationError('File structure is too complex.') from exc

def read_json(path,limit=24_000_000):
    with Path(path).open('rb') as stream:
        raw=stream.read(limit+1)
    if len(raw)>limit:raise ValidationError('File exceeds the supported size limit.')
    try:return parse_json(raw.decode('utf-8-sig'))
    except UnicodeDecodeError as exc:raise ValidationError('Use a UTF-8 JSON file.') from exc

def atomic_json(path,data,limit=50_000_000):
    # Serialize before touching the destination. Unique temporary names prevent
    # collisions, flush before replace, and never put partial JSON in the main file.
    encoded=json.dumps(data,indent=2,allow_nan=False).encode('utf-8')
    if len(encoded)>limit:raise ValidationError('Saved data exceeds the supported size limit. Export and remove unused zones or routes.')
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);temp=None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent,prefix='.'+path.name+'.',suffix='.tmp',delete=False) as out:
            temp=Path(out.name);out.write(encoded);out.flush();os.fsync(out.fileno())
        os.replace(temp,path)
    finally:
        if temp is not None and temp.exists():temp.unlink()

def plain_image(image):
    if min(image.size)<4 or image.width*image.height>MAX_IMAGE_PIXELS:raise ValidationError('Invalid image dimensions.')
    clean=Image.new('RGB',image.size);clean.paste(image.convert('RGB'));return clean

def safe_image(source,minimum=80):
    with Image.open(source) as image:
        if min(image.size)<minimum or image.width*image.height>MAX_IMAGE_PIXELS:raise ValidationError('Use an image with enough detail and at most 25 million pixels.')
        image.load();return plain_image(image)

def friendly_error(exc):
    if isinstance(exc,OSError):return 'Cannot read or save this file. Check permissions, available space and whether another app is using it.'
    if isinstance(exc,(json.JSONDecodeError,UnicodeError,RecursionError)):return 'Invalid file. Check its format and try again.'
    if isinstance(exc,ValidationError):
        message=str(exc)
        if len(message)<=220 and not re.search(r'[/\\]|@|https?:|[\r\n]|[\x00-\x1f]',message):return message
        return 'Invalid data. Check the map image or import format and try again.'
    return 'This operation failed. Try again, or restart the tool. Your saved files have not been reset.'
