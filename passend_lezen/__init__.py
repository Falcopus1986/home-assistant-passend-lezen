"""Optional Music Assistant audiobook provider backed by Home Assistant."""
from collections.abc import AsyncGenerator
from urllib.parse import urlsplit
import aiohttp
from music_assistant.models.music_provider import MusicProvider
from music_assistant_models.enums import ArtistType,ContentType,MediaType,ProviderFeature,StreamType
from music_assistant_models.media_items import Artist,Audiobook,AudioFormat,MediaItemChapter,ProviderMapping,UniqueList
from music_assistant_models.streamdetails import MultiPartPath,StreamDetails
from music_assistant_models.errors import MediaNotFoundError,ProviderUnavailableError

FEATURES={ProviderFeature.LIBRARY_AUDIOBOOKS,ProviderFeature.LIBRARY_ARTISTS}

def valid_url(value: str) -> str:
    parsed=urlsplit(value.rstrip('/'))
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path:
        raise ValueError('Vul alleen de basis-URL van Home Assistant in.')
    return value.rstrip('/')

async def check_connection(url: str,token: str) -> bool:
    try:
        url=valid_url(url)
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
            async with session.post(url+'/api/services/passend_lezen/ma_bibliotheek?return_response',json={},headers={'Authorization':'Bearer '+token}) as response:
                result=await response.json()
                return response.status==200 and isinstance(result.get('service_response',{}).get('books'),list)
    except (ValueError,aiohttp.ClientError,TimeoutError,KeyError):return False

async def setup(mass,manifest,config):
    return PassendLezen(mass,manifest,config,FEATURES)

class PassendLezen(MusicProvider):
    async def _call(self,service,data):
        base=valid_url(str(self.get_setup_value('ha_url')))
        token=str(self.get_setup_value('ha_token'))
        try:
            async with self.mass.http_session.post(base+'/api/services/passend_lezen/'+service+'?return_response',json=data,headers={'Authorization':'Bearer '+token},timeout=aiohttp.ClientTimeout(total=120)) as response:
                if response.status!=200:raise ProviderUnavailableError('Home Assistant of Passend Lezen is niet beschikbaar.')
                return (await response.json())['service_response']
        except (aiohttp.ClientError,KeyError,TimeoutError) as exc:
            raise ProviderUnavailableError('Passend Lezen is tijdelijk niet bereikbaar.') from exc

    def _mapping(self,item_id):
        return {ProviderMapping(item_id=item_id,provider_domain=self.domain,provider_instance=self.instance_id)}

    def _author(self,name):
        return Artist(item_id=name,provider=self.instance_id,name=name,artist_type=ArtistType.AUTHOR,provider_mappings=self._mapping(name))

    def _book(self,row,detail=None):
        book=Audiobook(item_id=row['id'],provider=self.instance_id,name=row['title'],provider_mappings=self._mapping(row['id']),duration=int(detail['duration']) if detail else 0)
        if row.get('author'):book.authors.set([self._author(row['author'])])
        book.metadata.description=row.get('description')
        if row.get('genres'):book.metadata.genres={str(row['genres'])}
        if detail:
            book.metadata.chapters=[MediaItemChapter(position=i,name=c['label'],start=c['start'],end=c['end']) for i,c in enumerate(detail['chapters'],1)]
            book.resume_position_ms=detail['progress_ms']
        return book

    async def get_library_audiobooks(self) -> AsyncGenerator[Audiobook]:
        data=await self._call('ma_bibliotheek',{})
        for row in data['books']:yield self._book(row)

    async def get_audiobook(self,prov_audiobook_id:str) -> Audiobook:
        detail=await self._call('ma_boek',{'book_id':prov_audiobook_id})
        return self._book(detail['book'],detail)

    async def get_library_artists(self) -> AsyncGenerator[Artist]:
        data=await self._call('ma_bibliotheek',{})
        for name in sorted({b['author'] for b in data['books'] if b.get('author')}):yield self._author(name)

    async def get_artist(self,prov_artist_id:str) -> Artist:
        data=await self._call('ma_bibliotheek',{})
        if prov_artist_id not in {b['author'] for b in data['books'] if b.get('author')}:
            raise MediaNotFoundError('Auteur niet op de boekenplank.')
        return self._author(prov_artist_id)

    async def get_stream_details(self,item_id:str,media_type:MediaType) -> StreamDetails:
        if media_type!=MediaType.AUDIOBOOK:raise MediaNotFoundError('Alleen audioboeken worden ondersteund.')
        detail=await self._call('ma_boek',{'book_id':item_id,'streams':True})
        parts=[MultiPartPath(path=p['url'],duration=p['duration']) for p in detail['parts']]
        if not parts:raise MediaNotFoundError('Dit boek heeft geen afspeelbare onderdelen.')
        return StreamDetails(provider=self.instance_id,item_id=item_id,audio_format=AudioFormat(content_type=ContentType.MP3),media_type=MediaType.AUDIOBOOK,stream_type=StreamType.HTTP,duration=int(detail['duration']),path=parts[0].path if len(parts)==1 else parts,can_seek=True,allow_seek=True,expiration=3600)

    async def on_played(self,media_type:MediaType,prov_item_id:str,fully_played:bool,position:int,media_item,is_playing:bool=False) -> None:
        if media_type==MediaType.AUDIOBOOK and position is not None:
            await self._call('ma_voortgang',{'book_id':prov_item_id,'seconds':max(0,position)})
