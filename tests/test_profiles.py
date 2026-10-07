"""Portable regressions using generated pictures, never personal game assets."""
import base64
import copy
import hashlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image, ImageDraw

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import profiles
from profiles import ProfileStore, reference_id, matching_reference
from security import ValidationError, atomic_json, parse_json, read_json
from routes import REFERENCE, decode_route


def picture():
    image=Image.new('RGB',(180,140),'#263247')
    draw=ImageDraw.Draw(image)
    draw.line([(10,25),(160,120),(15,115)],fill='#40dbf1',width=5)
    draw.rectangle((35,20,65,60),fill='#c3a1ff')
    return image


def png(image,level=6,metadata=False):
    stream=io.BytesIO()
    options={'compress_level':level}
    if metadata:
        exif=Image.Exif();exif[270]='private-location';options['exif']=exif
    image.save(stream,format='PNG',**options)
    return stream.getvalue()


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.root=Path(self.temporary.name)
        self.assets=self.root/'assets';self.assets.mkdir()
        self.image=picture()
        (self.assets/'reference.png').write_bytes(png(self.image))
        atomic_json(self.assets/'starter-nodes.json',[])
        atomic_json(self.assets/'seed.json',{'welcome':True,'name':'Welcome'})
        self.store=ProfileStore(self.root/'data',self.assets)

    def tearDown(self):self.temporary.cleanup()

    def test_pixel_identity_survives_encoding_and_metadata(self):
        encodings=[png(self.image,1),png(self.image,9,True)]
        self.assertNotEqual(encodings[0],encodings[1])
        for raw in encodings:
            with Image.open(io.BytesIO(raw)) as image:
                self.assertEqual(reference_id(image),reference_id(self.image))
        changed=self.image.copy();changed.putpixel((0,0),(1,2,3))
        self.assertNotEqual(reference_id(changed),reference_id(self.image))
        self.assertNotEqual(reference_id(self.image.resize((140,180))),reference_id(self.image))

    def test_old_png_identity_loads_under_another_encoder(self):
        zone=self.store.active;path=self.store.image_path(zone)
        raw=png(self.image,1,True);path.write_bytes(raw)
        old='map-'+hashlib.sha256(raw).hexdigest()[:24]
        zone['reference']=old;zone['routes'][0]['reference']=old
        self.store.write();before=self.store.path.read_bytes()
        with patch.object(profiles,'image_bytes',side_effect=lambda image:png(image,9)):
            reopened=ProfileStore(self.store.folder,self.assets)
            self.assertEqual(reopened.active['reference'],old)
            self.assertEqual(reopened.path.read_bytes(),before)
            exported=self.root/'shared.json';reopened.export(reopened.active,exported)
            shared=read_json(exported)
            self.assertEqual(shared['profile']['reference'],reference_id(self.image))
            self.assertNotIn('private-location',exported.read_text())
            self.assertEqual(reopened.import_file(exported)['reference'],reference_id(self.image))
        # Opening the old save alone never resets or rewrites it.
        self.assertEqual(zone['id'],reopened.profiles[0]['id'])

    def test_original_legacy_identity_uses_pixels(self):
        zone=self.store.active;zone['reference']=REFERENCE;zone['routes'][0]['reference']=REFERENCE
        self.store.write()
        with patch.object(profiles,'LEGACY_PIXEL_REFERENCE',reference_id(self.image)),patch.object(profiles,'image_bytes',side_effect=lambda image:png(image,1)):
            reopened=ProfileStore(self.store.folder,self.assets)
            self.assertEqual(reopened.active['reference'],REFERENCE)
            path=self.root/'legacy.json';reopened.export(reopened.active,path)
            self.assertEqual(reopened.import_file(path)['reference'],REFERENCE)
            self.assertFalse(matching_reference(Image.new('RGB',self.image.size,'red'),REFERENCE))

    def test_routes_recognize_verified_old_and_pixel_aliases(self):
        raw=png(self.image,1)
        old='map-'+hashlib.sha256(raw).hexdigest()[:24]
        aliases=profiles.reference_aliases(self.image,raw)
        self.assertIn(old,aliases);self.assertIn(reference_id(self.image),aliases)
        self.assertNotIn(REFERENCE,aliases)
        self.assertNotIn('map-unverified',aliases)
        route=copy.deepcopy(self.store.active['routes'][0]);route['reference']=old
        self.assertEqual(decode_route(route,old,self.image.size)['reference'],old)

    def test_wrong_saved_map_is_rejected_and_not_changed(self):
        # No backup on the first save; error must explain the map check.
        original=self.store.path.read_bytes()
        self.store.image_path(self.store.active).write_bytes(png(Image.new('RGB',self.image.size,'red')))
        with self.assertRaisesRegex(ValidationError,'map picture does not match'):
            ProfileStore(self.store.folder,self.assets)
        self.assertEqual(self.store.path.read_bytes(),original)

    def test_corrupt_main_recovers_backup_preserving_original(self):
        self.store.active['name']='Previous zone';self.store.write()
        self.store.active['name']='Newest zone';self.store.write()
        backup=self.store.path.with_name('profiles.backup.json').read_bytes()
        self.store.path.write_text('{bad')
        reopened=ProfileStore(self.store.folder,self.assets)
        self.assertTrue(reopened.recovered);self.assertEqual(reopened.active['name'],'Previous zone')
        copies=list(self.store.folder.glob('profiles.damaged-*.json'))
        self.assertEqual(len(copies),1);self.assertEqual(copies[0].read_text(),'{bad')
        reopened.write()
        self.assertEqual(self.store.path.with_name('profiles.backup.json').read_bytes(),backup)

    def test_profile_import_is_private_and_rejects_wrong_map(self):
        zone=self.store.active
        zone['model_preferences']={'prompt':'secret prompt'};zone['planning']={'key':'secret'}
        zone['api_key']='secret key'
        path=self.root/'share.json';self.store.export(zone,path)
        shared=read_json(path)
        self.assertNotIn('secret',path.read_text())
        with Image.open(io.BytesIO(base64.b64decode(shared['image']))) as image:self.assertFalse(image.info)
        shared['profile']['reference']='map-not-the-image';atomic_json(path,shared)
        before=self.store.path.read_bytes()
        with self.assertRaises(ValidationError):self.store.import_file(path)
        self.assertEqual(self.store.path.read_bytes(),before);self.assertEqual(len(self.store.profiles),1)

    def test_older_raw_png_profile_imports_and_normalizes(self):
        path=self.root/'share.json';self.store.export(self.store.active,path);shared=read_json(path)
        raw=png(self.image,1,True);old='map-'+hashlib.sha256(raw).hexdigest()[:24]
        shared['image']=base64.b64encode(raw).decode();shared['profile']['reference']=old
        shared['profile']['routes'][0]['reference']=old;atomic_json(path,shared)
        imported=self.store.import_file(path)
        self.assertEqual(imported['reference'],reference_id(self.image))
        self.assertEqual(imported['routes'][0]['reference'],reference_id(self.image))
        with Image.open(self.store.image_path(imported)) as image:self.assertFalse(image.info)

    def test_invalid_json_and_geometry_remain_rejected(self):
        for raw in ('{"x":1,"x":2}','{"x":NaN}','['*80+'0'+']'*80):
            with self.subTest(raw=raw[:20]),self.assertRaises(ValueError):parse_json(raw)
        path=self.root/'share.json';self.store.export(self.store.active,path);shared=read_json(path)
        shared['profile']['crop']=[-1,0,180,140];atomic_json(path,shared)
        with self.assertRaises(ValidationError):self.store.import_file(path)

    def test_two_profiles_and_routes_survive_restart(self):
        first=self.store.active['id'];zone=self.store.create('Second zone',self.image,crop=(10,10,170,130))
        route=copy.deepcopy(zone['routes'][0]);route['id']='saved-route';route['name']='Gem route'
        route['nodes']=[{'X':20,'Y':20,'Kind':'Crystal'}];zone['routes'].append(route);self.store.write()
        reopened=ProfileStore(self.store.folder,self.assets)
        self.assertEqual(len(reopened.profiles),2)
        self.assertEqual(reopened.profiles[0]['id'],first)
        self.assertEqual(reopened.active['routes'][1]['nodes'][0]['Kind'],'Crystal')


if __name__=='__main__':unittest.main()
