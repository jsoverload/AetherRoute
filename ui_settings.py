"""Local application preferences; never part of profile or model exports."""
from pathlib import Path
from security import ValidationError, atomic_json, read_json, plain_text

DEFAULTS=dict(developer_mode=False,launcher_enabled=True,start_collapsed=True,main_topmost=True,last_map='',launcher_margin=[18,36])

def clean_settings(data):
    if not isinstance(data,dict):raise ValidationError('Invalid application preferences.')
    result={}
    for key in ('developer_mode','launcher_enabled','start_collapsed','main_topmost'):
        value=data.get(key,DEFAULTS[key])
        if type(value)!=bool:raise ValidationError('Application options must use true or false.')
        result[key]=value
    result['last_map']=plain_text(data.get('last_map',''),100)
    margin=data.get('launcher_margin',DEFAULTS['launcher_margin'])
    if not isinstance(margin,list) or len(margin)!=2 or any(type(v)!=int or not 0<=v<=10000 for v in margin):raise ValidationError('Invalid launcher position.')
    result['launcher_margin']=list(margin)
    return result

class Preferences:
    def __init__(self,folder):
        self.path=Path(folder)/'app-settings.json'
        self.data=clean_settings(read_json(self.path,16000) if self.path.exists() else {})
    def update(self,**changes):
        updated=clean_settings(dict(self.data,**changes));atomic_json(self.path,updated,limit=16000);self.data=updated
