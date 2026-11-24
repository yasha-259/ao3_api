import functools
import os
import pathlib
import pickle
import datetime
import re
import time
from functools import cached_property

import requests
from bs4 import BeautifulSoup

from . import threadable, utils
from .requester import requester


def get(self, *args, **kwargs):
        """Request a web page and return a Response object"""  

        req = requester.request("get", *args, **kwargs)

        if req.status_code == 429:
            raise utils.HTTPError("We are being rate-limited. Try again in a while or reduce the number of requests")
        return req
        
def request(url):
        
        """Request a web page and return a BeautifulSoup object.
        
        Args:
        url (str): Url to request
        
        Returns:
        bs4.BeautifulSoup: BeautifulSoup object representing the requested page's html
        """
        
        req = get(url)
        soup = BeautifulSoup(req.content, "lxml")
        return soup

def _download_languages():
    path = os.path.dirname(__file__)
    languages = []
    try:
        rsrc_path = os.path.join(path, "resources")
        if not os.path.isdir(rsrc_path):
            os.mkdir(rsrc_path)
        language_path = os.path.join(rsrc_path, "languages")
        if not os.path.isdir(language_path):
            os.mkdir(language_path)
        url = "https://archiveofourown.org/languages"
        print(f"Downloading from {url}")
        req = requester.request("get", url)
        soup = BeautifulSoup(req.content, "lxml")
        for dt in soup.find("dl", {"class": "language index group"}).findAll("dt"):
            if dt.a is not None: 
                alias = dt.a.attrs["href"].split("/")[-1]
            else:
                alias = None
            languages.append((dt.getText(), alias))
        with open(f"{os.path.join(language_path, 'languages')}.pkl", "wb") as file:
            pickle.dump(languages, file)
    except AttributeError:
        raise utils.UnexpectedResponseError("Couldn't download the desired resource. Do you have the latest version of ao3-api?")
    print(f"Download complete ({len(languages)} languages)")

def _download_fandom(fandom_key, name):
    path = os.path.dirname(__file__)
    fandoms = []
    try:
        rsrc_path = os.path.join(path, "resources")
        if not os.path.isdir(rsrc_path):
            os.mkdir(rsrc_path)
        fandom_path = os.path.join(rsrc_path, "fandoms")
        if not os.path.isdir(fandom_path):
            os.mkdir(fandom_path)
        url = f"https://archiveofourown.org/media/{fandom_key}/fandoms"
        print(f"Downloading from {url}")
        req = requester.request("get", url)
        soup = BeautifulSoup(req.content, "lxml")
        for fandom in soup.find("ol", {"class": "alphabet fandom index group"}).findAll("a", {"class": "tag"}):
            fandoms.append(fandom.getText())
        with open(f"{os.path.join(fandom_path, name)}.pkl", "wb") as file:
            pickle.dump(fandoms, file)
    except AttributeError:
        raise utils.UnexpectedResponseError("Couldn't download the desired resource. Do you have the latest version of ao3-api?")
    print(f"Download complete ({len(fandoms)} fandoms)")
 

_FANDOM_RESOURCES = {
    "anime_manga_fandoms": functools.partial(
        _download_fandom, 
        "Anime%20*a*%20Manga", 
        "anime_manga_fandoms"),
    "books_literature_fandoms": functools.partial(
        _download_fandom, 
        "Books%20*a*%20Literature", 
        "books_literature_fandoms"),
    "cartoons_comics_graphicnovels_fandoms": functools.partial(
        _download_fandom, 
        "Cartoons%20*a*%20Comics%20*a*%20Graphic%20Novels", 
        "cartoons_comics_graphicnovels_fandoms"),
    "celebrities_real_people_fandoms": functools.partial(
        _download_fandom, 
        "Celebrities%20*a*%20Real%20People", 
        "celebrities_real_people_fandoms"),
    "movies_fandoms": functools.partial(
        _download_fandom, 
        "Movies", 
        "movies_fandoms"),
    "music_bands_fandoms": functools.partial(
        _download_fandom, 
        "Music%20*a*%20Bands", 
        "music_bands_fandoms"),
    "other_media_fandoms": functools.partial(
        _download_fandom, 
        "Other%20Media", 
        "other_media_fandoms"),
    "theater_fandoms": functools.partial(
        _download_fandom, 
        "Theater", 
        "theater_fandoms"),
    "tvshows_fandoms": functools.partial(
        _download_fandom, 
        "TV%20Shows", 
        "tvshows_fandoms"),
    "videogames_fandoms": functools.partial(
        _download_fandom, 
        "Video%20Games", 
        "videogames_fandoms"),
    "uncategorized_fandoms": functools.partial(
        _download_fandom, 
        "Uncategorized%20Fandoms", 
        "uncategorized_fandoms")
}

_LANGUAGE_RESOURCES = {
    "languages": _download_languages
}

_RESOURCE_DICTS = [("fandoms", _FANDOM_RESOURCES),
                   ("languages", _LANGUAGE_RESOURCES)]

@threadable.threadable
def download(resource):
    """Downloads the specified resource.
    This function is threadable.

    Args:
        resource (str): Resource name

    Raises:
        KeyError: Invalid resource
    """
    
    for _, resource_dict in _RESOURCE_DICTS:
        if resource in resource_dict:
            resource_dict[resource]()
            return
    raise KeyError(f"'{resource}' is not a valid resource")

def get_resources():
    """Returns a list of every resource available for download"""
    
    d = {}
    for name, resource_dict in _RESOURCE_DICTS:
        d[name] = list(resource_dict.keys())
    return d

def has_resource(resource):
    """Returns True if resource was already download, False otherwise"""
    path = os.path.join(os.path.dirname(__file__), "resources")
    return len(list(pathlib.Path(path).rglob(resource+".pkl"))) > 0

@threadable.threadable
def download_all(redownload=False):
    """Downloads every available resource.
    This function is threadable."""
    
    types = get_resources()
    for rsrc_type in types:
        for rsrc in types[rsrc_type]:
            if redownload or not has_resource(rsrc):
                download(rsrc)

@threadable.threadable    
def download_all_threaded(redownload=False):
    """Downloads every available resource in parallel (about ~3.7x faster).
    This function is threadable."""
    
    threads = []
    types = get_resources()
    for rsrc_type in types:
        for rsrc in types[rsrc_type]:
            if redownload or not has_resource(rsrc):
                threads.append(download(rsrc, threaded=True))
    for thread in threads:
        thread.join()


#----------Get works from any page with pagination

def get_pagecount(url):
    """
    counts the available pages for a url.
    """
    page_one_url = f"{url}?page=1"
    soup = request(page_one_url)
    pages = soup.find("ol",{"aria-label": "Pagination"})
    if pages is None:
        return 1
    n = 1
    for li in pages.findAll("li"):
        text = li.getText()
        if text.isdigit():
            n = int(text)
    return n

def load_ids(url, works, page=1 ):
    """
    loads the ids of all works on a specified page. 
    """
    
    url = f"{url}?page={page}"
    workPage = request(url)
    worksRaw = workPage.find_all("li", {"role": "article"})
    
    for item in worksRaw:
            # authors = []
            workname = None
            workid = None
            for a in item.h4.find_all("a"):
                if a.attrs["href"].startswith("/works"):
                    workname = str(a.string)
                    workid = utils.workid_from_url(a["href"])
            if workname != None and workid != None:
                # this seems sketchy:
                works[workid]= workname

        
        
def get_work_ids(url, sleep = 3, start_page = 0, max_pages = None, page_count = None, timeout_sleep = 180): 
    
    """
    Gets work ids and work-titles from work-page-urls (i.e. Userpages or fandom-pages).
    Simply needs to end in /works (https://archiveofourown.org/tags/Pocket%20Monsters%20%7C%20Pokemon%20-%20All%20Media%20Types/works)

    Arguments: 
        url(str): 
        sleep (int): 
        start_page (int): 
        max_pages (int): 
        page_count (int): 
        timeout_sleep (int)

    Returns: 
        works (dict): a dictionary of workid and title  
    """
    start_url = f"{url}?page=1" #https://archiveofourown.org/users/<name>/pseuds/<name>/works
    works = {}
    if not page_count: 
        page_count = get_pagecount(url)

    # starts to loop through all the pages 
    for page in range(start_page, page_count):
        print(f"Processing page {page+1} of {page_count} pages.")
        
        if timeout_sleep is None:
                  load_ids(url,works= works, page=page+1 )
        else: 
            loaded = False 
            while loaded == False: 
                try: 
                    load_ids(url, works = works, page=page+1)
                    #print(f"Added works on {page+1} of {}.")
                    loaded = True 

                except utils.HTTPError:
                            print(f"Loading being rate limited, sleeping for {timeout_sleep} seconds")
                            time.sleep(timeout_sleep)

        
        # Check for maximum history page load
        if max_pages is not None and page >= max_pages:
            return works

        # Again attempt to avoid rate limiter, sleep for a few
        # seconds between page requests.
        if sleep is not None and sleep > 0:
            print(f"Sleeping for {sleep} seconds")
            time.sleep(sleep)

    return works






