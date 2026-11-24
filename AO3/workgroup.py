from datetime import date
from datetime import datetime
from functools import cached_property
import datetime
import re
import time
from bs4 import BeautifulSoup

from . import threadable, utils
from .common import get_work_from_banner
from .requester import requester
from .users import User
from .works import Work
from .metadata import work_metadata_from_soup


class Workgroup:
    def __init__(self, url, session=None, load=True, html = None, filter = False):
        """Creates a new 'Work Group' object from a url

        Args:
            url (str): ao3-url for a group of works; can be user-work-page, search results etc; can also be series or collection url !!
                        should now in theory, maybe just maybe, also work with bookmark/history/subscription pages (remove page counter though)
                        i.e. url = session._subscriptions_url.format(session.username,1).replace("?page=1","")
                        _subscriptions_url = "https://archiveofourown.org/users/{0}/subscriptions?page={1:d}"
                        _bookmarks_url = "https://archiveofourown.org/users/{0}/bookmarks?page={1:d}"
                        _history_url = "https://archiveofourown.org/users/{0}/readings?page={1:d}"
            session (AO3.Session, optional): Session object. Defaults to None.
            load (bool, optional): If true, loaded on initialization. Defaults to True.

        Raises:
            utils.InvalidIdError: Invalid url
        """

        self._session = session
        #self._soup_start = None
        

        self.group_url = url

        pg_no = re.search('page=(\d*)', url)
        if pg_no: 
            pg_no= pg_no.group(1)
        else pg_no=1    
        self.input_page=pg_no
        
        self._work_ids = None
        self._pages = None
        self._name = None
        self._filter = filter 
        if "&" in url:
            self._delimiter = "&"
        else: 
             self._delimiter = "?"

        self._urls = None 
        self._pages_html = None 
        self._works_dict= None

        self._soup = None
        if html: 
            self._soup = BeautifulSoup(html, "lxml")
            self._pages = self.pages
            self._name = self.name
            self._urls = self.url
            self._pages_html = {self.input_page:self._soup}
            self._works_dict= {}

        if load:
            self.reload()
            
    def __eq__(self, other):
        return isinstance(other, __class__) and other.group_url == self.group_url
    
    def __repr__(self):
        try:
            return f"<Group of works from [{self.name}]>"
        except:
            return f"<Group of works from [{self.group_url}]>"
        
    def __getstate__(self):
        d = {}
        for attr in self.__dict__:
            if isinstance(self.__dict__[attr], BeautifulSoup):
                d[attr] = (self.__dict__[attr].encode(), True)
            else:
                d[attr] = (self.__dict__[attr], False)
        return d

    def __setstate__(self, d):
        for attr in d:
            value, issoup = d[attr]
            if issoup:
                self.__dict__[attr] = BeautifulSoup(value, "lxml")
            else:
                self.__dict__[attr] = value
                
    def set_session(self, session):
        """Sets the session used to make requests for this series

        Args:
            session (AO3.Session/AO3.GuestSession): session object
        """
        
        self._session = session 
        
    @threadable.threadable
    def reload(self):
        """
        Loads information about this series.
        This function is threadable.
        """
        
        for attr in self.__class__.__dict__:
            if isinstance(getattr(self.__class__, attr), cached_property):
                if attr in self.__dict__:
                    delattr(self, attr)
                    
        #self._soup_start = self.request(f"{self.group_url}&page=1")
        self._soup = self.request(f"{self.group_url}")
        print(f"{self.group_url}")
        # ??? self._soup_start = self.request(self.url_start)

        if "Error 404" in self._soup.text:
            raise utils.InvalidIdError("Cannot find page")
        if "Error 503" in self._soup.text:
            raise utils.HTTPError("Page was responding too slowly")
        self._pages = self.pages
        self._name = self.name
        self._urls = self.urls
        self._pages_html = {1:self._soup}
        self._works_dict= {}


    @cached_property
    def url_start(self):
        """Returns the URL to this series

        Returns:
            str: series URL
        """
        # for some reason sometimes ? and sometimes & is used ... 
        # find out when
        if self._filter: 
            return f"{self.group_url}&page=1"
        return f"{self.group_url}?page=1"

    @property
    def loaded(self):
        """Returns True if this series has been loaded"""
        return self._soup is not None

    # @property
    # def loaded_cache(self):
    #     """Returns True if this series has been loaded"""
    #     return self._soup is not None    
        
    @cached_property
    def authenticity_token(self):
        """Token used to take actions that involve this work"""
        
        if not self.loaded:
            return None
        
        token = self._soup.find("meta", {"name": "csrf-token"})
        return token["content"]

    @cached_property
    def name(self):
        """"""

        if not self.loaded:
            return None

        #heading = self._soup.find("h2", {"class": "heading"})
        heading = self._soup.find("h2", class_="heading")
        if heading: 
            heading=heading.text.strip()
            
        return heading

    @cached_property
    def pages(self):
        #print(self._soup)
        pagessoup = self._soup.find("ol", class_="pagination actions pagy")
        if pagessoup is None:
            return 1
        n = 1
        for li in pagessoup.find_all("li"):
            text = li.getText()
            if text.isdigit():
                n = int(text)

        if n > 10:
            print(f"WARNING: this group of works contains more than {(n-1)*20} items on {n} pages.")
        return n

    @cached_property
    def urls(self):

        if self._urls is None:
          self._urls = {}#{1: self.group_url}

        # delimiter = "?"
        # if self._filter: 
        #     delimiter = "&"

        pages = self.pages
        if not pages: 
            pages = 1

        # if pages ==1: 
        #     return self._urls

        for i in range(1,pages+1):#(2,pages+1):
            self._urls[i] = f"{self.group_url}{self._delimiter}page={i}"
            return self._urls

    # ****************************************
    #               WORKING HERE             *
    # ****************************************
    def get_works(self,start_page=1, end_page=None, max_pages=None,sleep=30, timeout_sleep=120,skip_request=False):
        if self._works_dict is None:
            self._works_dict={}

        npages = self.pages
        if not end_page: 
            end_page = npages
        if start_page > npages:
            print(f"start_page out of range; Starting on last page no.{npages}.")
            start_page = npages
        if end_page > npages:
            print(f"end_page out of range; Ending on last page no.{npages}.")
            end_page = npages
        if start_page > end_page:
            print(f"start_page after end_page; Ending on start_page no.{start_page}.")
            end_page = start_page
        # if max_pages > self.pages:
        #     max_pages = self.pages

        pages_to_process = list(range(start_page,end_page+1))
        if max_pages: 
            pages_to_process = pages_to_process[:max_pages]
        
        print(f"Starting to process ... # Page(s): {len(pages_to_process)}")    
        counter = 1

        # Sonderfall: page 1 is already loaded from pages!! return has to be here positioned here 
        # if len(pages_to_process)==1 and pages_to_process[0]==1:
        #     print(f"Processing page {counter} of {len(pages_to_process)}")
        #     return self._works_dict
        #     ## ADD: retrieve data from soup     

        #soups_dict = self._pages_html 
        urls = self._urls
        
        for page in pages_to_process: 
            tries = 1
            print(f"Processing page {counter} of {len(pages_to_process)}")
            loaded = False
            html = self._pages_html.get(page, None)
            if html: 
                loaded = True
            if skip_request: 
                loaded = True
                sleep=0
            while loaded == False and tries<11:
                url = urls[page]
                try:
                    print(f"fetching data from '{url}'" )    
                    html = self.request(url)
                    loaded = True
                    self._pages_html[page]=html
                except utils.HTTPError:
                    print(f"Trial {tries} of 10")
                    print(f"Loading being rate limited, sleeping for {timeout_sleep} seconds")
                    time.sleep(timeout_sleep)
                    tries+=1
            
            if html:
                self.works_from_soup(html)


            if sleep is not None and sleep > 0:
                    print(f"Sleeping for {sleep} seconds")
                    time.sleep(sleep)
            counter+=1        

        return self._works_dict


    # ****************************************

    def get_work_ids(self, hist_sleep=3, start_page=1, max_pages=None, timeout_sleep=60):
        """
        Arguments:
            sleep (int): The time to wait between page requests
            timeout_sleep (int): The time to wait after the rate limit is hit

        Returns:
            works (list): All marked for later works
        """

        if self._work_ids is None:

          self._work_ids = {}
          #self._pagecount = self.pages()

          for page in range(start_page, self.pages):
                print(f"Processing page {page+1} of {self.pages} pages.")
                #print(str(page))
                # If we are attempting to recover from errors then
                # catch and loop, otherwise just call and go
                if timeout_sleep is None:
                  self._load_work_ids(page=page+1)

                else:
                    loaded=False
                    while loaded == False:
                        try:
                            self._load_work_ids(page=page+1)
                            print(f"Read page {page+1}")
                            loaded = True

                        except utils.HTTPError:
                            print(f"Loading being rate limited, sleeping for {timeout_sleep} seconds")
                            time.sleep(timeout_sleep)


                  # Check for maximum history page load
                if max_pages is not None and page >= max_pages:
                    return self._work_ids 

                # Again attempt to avoid rate limiter, sleep for a few
                # seconds between page requests.
                if hist_sleep is not None and hist_sleep > 0:
                    print(f"Sleeping for {hist_sleep} seconds")
                    time.sleep(hist_sleep)
                    
        return self._work_ids 
    
    def _load_work_ids_working(self, page=1):   
        #url = f"{self.group_url}&page={page}"
        if page ==1: 
            soup = self._soup
            print("using loaded page")
        else:     
            url = f"{self.group_url}?page={page}"
            if self.filter: 
                url = f"{self.group_url}&page={page}"
            print(f"fetching data from '{url}'" )    
            soup = self.request(url)
        #all_works_soup = soup.find("ol", {"class": ["index", "group"]})
        #works_soup = all_works_soup.find_all("li", {"role": "article"})
        works_soup = soup.find_all("li", {"role": "article"})

        #read_later = worksRaw.find("ol", {"class": "reading work index group"})

        for item in works_soup:
            # authors = []
            workname = None
            workid = None
            for a in item.h4.find_all("a"):
                if a.attrs["href"].startswith("/works"):
                    workname = str(a.string)
                    workid = utils.workid_from_url(a["href"])
                    
            if workname is not None and workid is not None:
                self._work_ids[workid]= workname

    def works_from_soup(self, soup):   
        works = soup.find_all('li', role="article")
        if works:
            for work in works: 
                #work_metadata= id_user(work)
                #work_id = work_metadata["id"]
                # add required tags
                #work_metadata = work_metadata | required_tags(work)| title_author(work)| stats(work)| tags(work)| fand(work)| summary(work)| some_date(work)| series(work) | last_visited(work) | bookmark_info(work)
                work_id, work_metadata = work_metadata_from_soup(work)
                if work_id is not None:
                    self._works_dict[int(work_id)]= work_metadata
        else: 
            print("No works in html")            

    def  _load_work_ids(self, page=1):   
        
        url = f"{self.group_url}?page={page}"
        if self._filter: 
          url = f"{self.group_url}&page={page}"

        soup = self.request(url)
        #all_works_soup = soup.find("ol", {"class": ["index", "group"]})
        #works_soup = all_works_soup.find_all("li", {"role": "article"})
        #works_soup = soup.find_all("li", {"role": "article"})
        works = soup.find_all('li', role="article")
        #read_later = worksRaw.find("ol", {"class": "reading work index group"})

        for work in works: 

            work_metadata= id_user(work)

            work_id = work_metadata["id"]
    
            # add required tags
            work_metadata = work_metadata | required_tags(work)| title_author(work)| stats(work)| tags(work)| fand(work)| summary(work)| some_date(work)| series(work) | last_visited(work) | bookmark_info(work)

                    
            if work_id is not None:
                self._work_ids[int(work_id)]= work_metadata

    
    def get(self, *args, **kwargs):
        """Request a web page and return a Response object"""  
        
        if self._session is None:
            req = requester.request("get", *args, **kwargs)
        else:
            req = requester.request("get", *args, **kwargs, session=self._session.session)
        if req.status_code == 429:
            raise utils.HTTPError("We are being rate-limited. Try again in a while or reduce the number of requests")
        return req

    def request(self, url):
        """Request a web page and return a BeautifulSoup object.

        Args:
            url (str): Url to request

        Returns:
            bs4.BeautifulSoup: BeautifulSoup object representing the requested page's html
        """

        req = self.get(url)
        soup = BeautifulSoup(req.content, "lxml")
        return soup
