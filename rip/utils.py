"""Utility functions for RipCore."""

import re

from streamrip.constants import AGENT
from streamrip.utils import gen_threadsafe_session

interpreter_artist_regex = re.compile(r"getSimilarArtist\(\s*'(\w+)'")


def extract_interpreter_url(url: str) -> str:
    """Extract artist ID from a Qobuz interpreter url.

    :param url: Urls of the form "https://www.qobuz.com/us-en/interpreter/{artist}/download-streaming-albums"
    :type url: str
    :rtype: str
    """
    session = gen_threadsafe_session({"User-Agent": AGENT})
    r = session.get(url)
    match = interpreter_artist_regex.search(r.text)
    if match:
        return match.group(1)

    raise Exception(
        "Unable to extract artist id from interpreter url. Use a "
        "url that contains an artist id."
    )

