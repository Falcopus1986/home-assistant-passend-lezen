"""Connect to Home Assistant; Passend Lezen credentials stay there."""
from music_assistant_models.config_entries import ConfigEntry
from music_assistant_models.enums import ConfigEntryType
from music_assistant.models.setup_flow import SetupSession

async def run_setup(session: SetupSession) -> None:
    fields=[
        ConfigEntry(key='ha_url',type=ConfigEntryType.STRING,label='Home Assistant URL',required=True,default_value='http://homeassistant.local:8123'),
        ConfigEntry(key='ha_token',type=ConfigEntryType.SECURE_STRING,label='Home Assistant toegangstoken',required=True),
    ]
    errors=None
    while True:
        values=await session.form(fields,step_id='connection',errors=errors,last_step=True)
        from . import check_connection
        if not await check_connection(str(values['ha_url']),str(values['ha_token'])):
            errors={'base':'Home Assistant of Passend Lezen is niet bereikbaar'}
            continue
        await session.finish(values)
        return
