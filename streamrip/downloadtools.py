import asyncio
import logging
import os
import re
from tempfile import gettempdir
from typing import Callable, Dict, Iterable, List, Optional

import aiofiles
import aiohttp

from .exceptions import NonStreamable
from .utils import gen_threadsafe_session

logger = logging.getLogger("streamrip")


class DownloadStream:
    """An iterator over chunks of a stream.

    Usage:

        >>> stream = DownloadStream('https://google.com', None)
        >>> with open('google.html', 'wb') as file:
        >>>     for chunk in stream:
        >>>         file.write(chunk)

    """

    is_encrypted = re.compile("/m(?:obile|edia)/")

    def __init__(
        self,
        url: str,
        source: str = None,
        params: dict = None,
        headers: dict = None,
        item_id: str = None,
    ):
        """Create an iterable DownloadStream of a URL.

        :param url: The url to download
        :type url: str
        :param params: Parameters to pass in the request
        :type params: dict
        :param headers: Headers to pass in the request
        :type headers: dict
        """
        self.source = source
        self.session = gen_threadsafe_session(headers=headers)

        self.id = item_id
        if isinstance(self.id, int):
            self.id = str(self.id)

        if params is None:
            params = {}

        self.request = self.session.get(
            url, allow_redirects=True, stream=True, params=params
        )
        self.file_size = int(self.request.headers.get("Content-Length", 0))

        if self.file_size < 20000 and not self.url.endswith(".jpg"):
            import json

            try:
                info = self.request.json()
                try:
                    raise NonStreamable(f"{info['error']} - {info['message']}")
                except KeyError:
                    raise NonStreamable(info)

            except json.JSONDecodeError:
                raise NonStreamable("File not found.")

    def __iter__(self) -> Iterable:
        """Iterate through chunks of the stream.

        :rtype: Iterable
        """
        return self.request.iter_content(chunk_size=1024)

    @property
    def url(self):
        """Return the requested url."""
        return self.request.url

    def __len__(self) -> int:
        """Return the value of the "Content-Length" header.

        :rtype: int
        """
        return self.file_size


class DownloadPool:
    """Asynchronously download a set of urls."""

    def __init__(
        self,
        urls: Iterable,
        tempdir: str = None,
        chunk_callback: Optional[Callable] = None,
    ):
        self.finished: bool = False
        # Enumerate urls to know the order
        self.urls = dict(enumerate(urls))
        self._downloaded_urls: List[str] = []
        # {url: path}
        self._paths: Dict[str, str] = {}
        self.task: Optional[asyncio.Task] = None

        if tempdir is None:
            tempdir = gettempdir()
        self.tempdir = tempdir

    async def getfn(self, url):
        path = os.path.join(self.tempdir, f"__streamrip_partial_{abs(hash(url))}")
        self._paths[url] = path
        return path

    async def _download_urls(self):
        async with aiohttp.ClientSession() as session:
            tasks = [
                asyncio.ensure_future(self._download_url(session, url))
                for url in self.urls.values()
            ]
            await asyncio.gather(*tasks)

    async def _download_url(self, session, url):
        filename = await self.getfn(url)
        logger.debug("Downloading %s", url)
        async with session.get(url) as response, aiofiles.open(filename, "wb") as f:
            # without aiofiles     3.6632679780000004s
            # with    aiofiles     2.504482839s
            await f.write(await response.content.read())

        if self.callback:
            self.callback()

        logger.debug("Finished %s", url)

    def download(self, callback=None):
        self.callback = callback
        asyncio.run(self._download_urls())

    @property
    def files(self):
        if len(self._paths) != len(self.urls):
            # Not all of them have downloaded
            raise Exception("Must run DownloadPool.download() before accessing files")

        return [
            os.path.join(self.tempdir, self._paths[self.urls[i]])
            for i in range(len(self.urls))
        ]

    def __len__(self):
        return len(self.urls)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        logger.debug("Removing tempfiles %s", self._paths)
        for file in self._paths.values():
            try:
                os.remove(file)
            except FileNotFoundError:
                pass

        return False
