import datetime
import re
import time
from functools import cached_property

import requests
from bs4 import BeautifulSoup

from . import threadable, utils
from .requester import requester
from .series import Series
from .users import User
from .works import Work


class GuestSession:
    """
    AO3 guest session object
    """

    def __init__(self):
        self.is_authed = False
        self.authenticity_token = None
        self.username = ""
        self.session = requests.Session()
        
    @property
    def user(self):
        return User(self.username, self, False)
    
    @threadable.threadable
    def comment(self, commentable, comment_text, oneshot=False, commentid=None):
        """Leaves a comment on a specific work.
        This function is threadable.

        Args:
            commentable (Work/Chapter): Commentable object
            comment_text (str): Comment text (must have between 1 and 10000 characters)
            oneshot (bool): Should be True if the work has only one chapter. In this case, chapterid becomes workid
            commentid (str/int): If specified, the comment is posted as a reply to this one. Defaults to None.

        Raises:
            utils.InvalidIdError: Invalid ID
            utils.UnexpectedResponseError: Unknown error
            utils.PseudoError: Couldn't find a valid pseudonym to post under
            utils.DuplicateCommentError: The comment you're trying to post was already posted
            ValueError: Invalid name/email

        Returns:
            requests.models.Response: Response object
        """
        
        response = utils.comment(commentable, comment_text, self, oneshot, commentid)
        return response

    
    @threadable.threadable
    def kudos(self, work):
        """Leave a 'kudos' in a specific work.
        This function is threadable.

        Args:
            work (Work): ID of the work

        Raises:
            utils.UnexpectedResponseError: Unexpected response received
            utils.InvalidIdError: Invalid ID (work doesn't exist)

        Returns:
            bool: True if successful, False if you already left kudos there
        """
        
        return utils.kudos(work, self)
        
    @threadable.threadable
    def refresh_auth_token(self):
        """Refreshes the authenticity token.
        This function is threadable.

        Raises:
            utils.UnexpectedResponseError: Couldn't refresh the token
        """
        
        # For some reason, the auth token in the root path only works if you're 
        # unauthenticated. To get around that, we check if this is an authed
        # session and, if so, get the token from the profile page.
        
        if self.is_authed:
            req = self.session.get(f"https://archiveofourown.org/users/{self.username}")
        else:
            req = self.session.get("https://archiveofourown.org")
            
        if req.status_code == 429:
            raise utils.HTTPError("We are being rate-limited. Try again in a while or reduce the number of requests")
            
        soup = BeautifulSoup(req.content, "lxml")
        token = soup.find("input", {"name": "authenticity_token"})
        if token is None:
            raise utils.UnexpectedResponseError("Couldn't refresh token")
        self.authenticity_token = token.attrs["value"]
        
    def get(self, *args, **kwargs):
        """Request a web page and return a Response object"""  
        
        if self.session is None:
            req = requester.request("get", *args, **kwargs)
        else:
            req = requester.request("get", *args, **kwargs, session=self.session)
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

    def post(self, *args, **kwargs):
        """Make a post request with the current session

        Returns:
            requests.Request
        """

        req = self.session.post(*args, **kwargs)
        if req.status_code == 429:
            raise utils.HTTPError("We are being rate-limited. Try again in a while or reduce the number of requests")
        return req
    
    def __del__(self):
        self.session.close()

class Session(GuestSession):
    """
    AO3 session object
    """

    def __init__(self, username, password):
        """Creates a new AO3 session object

        Args:
            username (str): AO3 username
            password (str): AO3 password

        Raises:
            utils.LoginError: Login was unsucessful (wrong username or password)
        """

        super().__init__()
        self.is_authed = True
        self.username = username
        self.url = "https://archiveofourown.org/users/%s"%self.username
        
        self.session = requests.Session()
        
        soup = self.request("https://archiveofourown.org/users/login")
        self.authenticity_token = soup.find("input", {"name": 'authenticity_token'})["value"]
        payload = {'user[login]': username,
                   'user[password]': password,
                   'authenticity_token': self.authenticity_token}
        post = self.post("https://archiveofourown.org/users/login", params=payload, allow_redirects=False)
        if not post.status_code == 302:
            raise utils.LoginError("Invalid username or password")

        self._subscriptions_url = "https://archiveofourown.org/users/{0}/subscriptions?page={1:d}"
        self._bookmarks_url = "https://archiveofourown.org/users/{0}/bookmarks?page={1:d}"
        self._history_url = "https://archiveofourown.org/users/{0}/readings?page={1:d}"
        
        self._bookmarks = None
        self._subscriptions = None
        self._history = None
        self._marked_for_later = None
        self._series_bookmarks = None 
        
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
        
    def clear_cache(self):
        for attr in self.__class__.__dict__:
            if isinstance(getattr(self.__class__, attr), cached_property):
                if attr in self.__dict__:
                    delattr(self, attr)
        self._bookmarks = None
        self._subscriptions = None
        
    @cached_property
    def _subscription_pages(self):
        url = self._subscriptions_url.format(self.username, 1)
        soup = self.request(url)
        pages = soup.find("ol", {"aria-label": "Pagination"})
        if pages is None:
            return 1
        n = 1
        for li in pages.findAll("li"):
            text = li.getText()
            if text.isdigit():
                n = int(text)
        return n
    
    def get_work_subscriptions(self, use_threading=False):
        """
        Get subscribed works. Loads them if they haven't been previously

        Returns:
            list: List of work subscriptions
        """
        
        subs = self.get_subscriptions(use_threading)
        return list(filter(lambda obj: isinstance(obj, Work), subs))
    
    def get_series_subscriptions(self, use_threading=False):
        """
        Get subscribed series. Loads them if they haven't been previously

        Returns:
            list: List of series subscriptions
        """
        
        subs = self.get_subscriptions(use_threading)
        return list(filter(lambda obj: isinstance(obj, Series), subs))
    
    def get_user_subscriptions(self, use_threading=False):
        """
        Get subscribed users. Loads them if they haven't been previously

        Returns:
            list: List of users subscriptions
        """
        
        subs = self.get_subscriptions(use_threading)
        return list(filter(lambda obj: isinstance(obj, User), subs))
    
    def get_subscriptions(self, use_threading=False):
        """
        Get user's subscriptions. Loads them if they haven't been previously

        Returns:
            list: List of subscriptions
        """
        self._subscription_pages= self._subscription_pages
        if self._subscriptions is None:
            if use_threading:
                self.load_subscriptions_threaded()
            else:
                self._subscriptions = []
                for page in range(self._subscription_pages):
                    self._load_subscriptions(page=page+1)
        return self._subscriptions
    
    @threadable.threadable
    def load_subscriptions_threaded(self):
        """
        Get subscribed works using threads.
        This function is threadable.
        """ 
        
        threads = []
        self._subscriptions = []
        for page in range(self._subscription_pages):
            threads.append(self._load_subscriptions(page=page+1, threaded=True))
        for thread in threads:
            thread.join()

    @threadable.threadable
    def _load_subscriptions(self, page=1):        
        url = self._subscriptions_url.format(self.username, page)
        print(url)
        soup = self.request(url)
        subscriptions = soup.find("dl", {"class": "subscription index group"})
        for sub in subscriptions.find_all("dt"):
            type_ = "work"
            user = None
            series = None
            workid = None
            workname = None
            authors = []
            for a in sub.find_all("a"):
                if "rel" in a.attrs.keys():
                    if "author" in a["rel"]:
                        authors.append(User(str(a.string), load=False))
                elif a["href"].startswith("/works"):
                    workname = str(a.string)
                    workid = utils.workid_from_url(a["href"])
                elif a["href"].startswith("/users"):
                    type_ = "user"
                    user = User(str(a.string), load=False)
                else:
                    type_ = "series"
                    workname = str(a.string)
                    series = int(a["href"].split("/")[-1])
            if type_ == "work":
                new = Work(workid, load=False)
                setattr(new, "title", workname)
                setattr(new, "authors", authors)
                self._subscriptions.append(new)
            elif type_ == "user":
                self._subscriptions.append(user)
            elif type_ == "series":
                new = Series(series, load=False)
                setattr(new, "name", workname)
                setattr(new, "authors", authors)
                self._subscriptions.append(new)

    @cached_property
    def _get_history_pages(self):
        url = self._history_url.format(self.username, 1)
        soup = self.request(url)
        pages = soup.find("ol", {"aria-label": "Pagination"})
        if pages is None:
            return 1
        n = 1
        for li in pages.findAll("li"):
            text = li.getText()
            if text.isdigit():
                n = int(text)
        return n

    def get_history(self, hist_sleep=3, start_page=0, max_pages=None, timeout_sleep=60, lite = False):
        """
        Get history works. Loads them if they haven't been previously.

        Arguments:
          hist_sleep (int to sleep between requests)
          start_page (int for page to start on, zero-indexed)
          max_pages  (int for page to end on, zero-indexed)
          timeout_sleep (int, if set will attempt to recovery from http errors, likely timeouts, if set to None will just attempt to load)

 takes two arguments the first hist_sleep is an int and is a sleep to run between pages of history to load to avoid hitting the rate limiter, the second is an int of the maximum number of pages of history to load, by default this is None so loads them all.

        Returns:
            list: List of tuples (Work, number-of-visits, datetime-last-visited)
        """
        
        if self._history is None:
            self._history = []
            if lite: 
                self._history = {}
            #self._history_pages= self._get_history_pages()
            for page in range(start_page, self._get_history_pages):
                print(f"Processing page {page+1} of {self._get_history_pages} pages.")
                # If we are attempting to recover from errors then
                # catch and loop, otherwise just call and go
                if timeout_sleep is None:
                    if lite: 
                        self._load_history_id(page=page+1)
                    else: 
                        self._load_history(page=page+1)
                    
                else:
                    loaded=False
                    while loaded == False:
                        try:
                            if lite: 
                                self._load_history_id(page=page+1)
                                loaded = True
                            else: 
                                self._load_history(page=page+1)
                                # print(f"Read history page {page+1}")
                                loaded = True

                        except utils.HTTPError:
                            # print(f"History being rate limited, sleeping for {timeout_sleep} seconds")
                            time.sleep(timeout_sleep)

                # Check for maximum history page load
                if max_pages is not None and page >= max_pages:
                    return self._history

                # Again attempt to avoid rate limiter, sleep for a few
                # seconds between page requests.
                if hist_sleep is not None and hist_sleep > 0:
                    time.sleep(hist_sleep)

        return self._history

    def _load_history(self, page=1):       
        url = self._history_url.format(self.username, page)
        soup = self.request(url)

        '''
        #try later: general purpose version: 
        all_works_soup =soup.find("ol", {"class": ["index", "group"]})
        works_soup = all_works_soup.find_all("li", {"role": "article"})
        '''
        
        history = soup.find("ol", {"class": "reading work index group"})
        for item in history.find_all("li", {"role": "article"}):
            authors = []
            workname = None
            workid = None
            #author = None
            for a in item.h4.find_all("a"):
                if a.attrs["href"].startswith("/works"):
                    workname = str(a.string)
                    workid = utils.workid_from_url(a["href"])
            for author in item.h4.find_all("a", attrs={"rel" : "author"}):
                    authors.append(author.text)

            visited_date = None
            visited_num = 1
            mfl = False
            status = None 
            for viewed in item.find_all("h4", {"class": "viewed heading" }):
                data_string = str(viewed)
                
                date_str = re.search('<span>Last visited:</span> (\d{2} .+ \d{4})', data_string)
                if date_str is not None:
                    raw_date = date_str.group(1)
                    date_time_obj = datetime.datetime.strptime(date_str.group(1), '%d %b %Y')
                    visited_date = date_time_obj
                    
                visited_str = re.search('Visited (\d+) times', data_string)
                if visited_str is not None:
                    visited_num = int(visited_str.group(1))
                    
                mfl_str = re.search('Marked for Later.', data_string)
                if mfl_str is not None:
                    mfl = True

                if re.search('Latest version.', data_string) is not None:
                    status = 'latest version'
                if re.search('Update available.', data_string) is not None:
                    status = 'update available'
                if re.search('Minor edits made since then.', data_string) is not None:
                    status = 'latest version, minor edits'                

            if workname != None and workid != None:
                new = Work(workid, load=False)
                if not authors: 
                    authors = ["Anonymous"]
                setattr(new, "title", workname)
                setattr(new, "authors", authors)
                # setattr(new, "authors", authors)
                hist_item = [ new, visited_num, visited_date, mfl, status]
                # print(hist_item)
                if new not in self._history:
                    self._history.append(hist_item)




    
    def _load_history_id (self, page=1):       
        '''a more lightweight version to load history: 
        returns only id and title but does not init works at all, 
        thus reducing requests to the archive. 

        could be extended to contain more metadata ....
        '''
        url = self._history_url.format(self.username, page)
        workPage = self.request(url)
        worksRaw = workPage.find_all("li", {"role": "article"})
        
        
        '''
        #try later: general purpose version: 
        all_works_soup =soup.find("ol", {"class": ["index", "group"]})
        works_soup = all_works_soup.find_all("li", {"role": "article"})
        '''
        
        #read_later = worksRaw.find("ol", {"class": "reading work index group"})

        for item in worksRaw:
            # authors = []
            workname = None
            workid = None
            for a in item.h4.find_all("a"):
                if a.attrs["href"].startswith("/works"):
                    workname = str(a.string)
                    workid = utils.workid_from_url(a["href"])
            #########---############
            # added: 
            last_read_blurb = item.find_all("h4", {"class": "viewed heading"}).text
            workname+= f" --- {last_read_blurb}"
            #########---############
                    
            if workname != None and workid != None:
                #new = Work(workid, load=False)
                #setattr(new, "title", workname)
                # setattr(new, "authors", authors)
                # hist_item = [ new, visited_num, visited_date ]
                # print(hist_item)
                #if new not in self._history:
                self._history[workid]= workname
                
    #@cached_property
    def _get_bookmark_pages(self):
        url = self._bookmarks_url.format(self.username, 1)
        soup = self.request(url)
        pages = soup.find("ol",{"aria-label": "Pagination"})
        if pages is None:
            return 1
        n = 1
        for li in pages.findAll("li"):
            text = li.getText()
            if text.isdigit():
                n = int(text)
        return n
    
    # def get_bookmarks(self, use_threading=False):
    #     """
    #     Get bookmarked works. Loads them if they haven't been previously

    #     Returns:
    #         list: List of tuples (workid, workname, authors)
    #     """
        
    #     if self._bookmarks is None:
    #         if use_threading:
    #             self.load_bookmarks_threaded()
    #         else:
    #             self._bookmarks = []
    #             for page in range(self._bookmark_pages):
    #                 self._load_bookmarks(page=page+1)
    #     return self._bookmarks

    def get_bookmarks(self, hist_sleep=3, start_page=0, max_pages=None, timeout_sleep=60, lite = False):
        
        """
        Kopie von get_history: jetzt auch mit sleep etc. 

        
        Get bookmarked works. Loads them if they haven't been previously

        Returns:
            list: List of tuples (workid, workname, authors)
        """

        if self._bookmarks is None:
            self._bookmarks = []
            if lite: 
                self._bookmarks = {}
                
            self._bookmark_pages= self._get_bookmark_pages()
            #self._soupDump = []
            for page in range(start_page, self._bookmark_pages):
                print(f"Processing page {page+1} of {self._bookmark_pages} pages.")
              
                # If we are attempting to recover from errors then
                # catch and loop, otherwise just call and go
                if timeout_sleep is None:
                    if lite: 
                        self._load_bookmarks_id(page=page+1)
                    else: 
                        self._load_bookmarks(page=page+1)

                else:
                    loaded=False
                    while loaded == False:
                        try:
                            if lite:   
                                self._load_bookmarks_id(page=page+1)
                                loaded = True
                                #print(f"Read history page {page+1}")
                            else:
                                self._load_bookmarks(page=page+1)
                                loaded = True

                        except utils.HTTPError:
                            print(f"History being rate limited, sleeping for {timeout_sleep} seconds")
                            time.sleep(timeout_sleep)


                  # Check for maximum history page load
                if max_pages is not None and page >= max_pages:
                    return self._bookmarks

                # Again attempt to avoid rate limiter, sleep for a few
                # seconds between page requests.
                if hist_sleep is not None and hist_sleep > 0:
                    print(f"Sleeping for {hist_sleep} seconds")
                    time.sleep(hist_sleep)
                    

        return self._bookmarks
    
    @threadable.threadable
    def load_bookmarks_threaded(self):
        """
        Get bookmarked works using threads.
        This function is threadable.
        """ 
        
        threads = []
        self._bookmarks = []
        self._bookmark_pages= self._get_bookmark_pages()
        for page in range(self._bookmark_pages):
            threads.append(self._load_bookmarks(page=page+1, threaded=True))
        for thread in threads:
            thread.join()
    
    #@threadable.threadable
    def _load_bookmarks(self, page=1):       
        url = self._bookmarks_url.format(self.username, page)
        soup = self.request(url)
        #print(soup)
        
        '''
        #try later: general purpose version: 
        all_works_soup =soup.find("ol", {"class": ["index", "group"]})
        works_soup = all_works_soup.find_all("li", {"role": "article"})
        '''
        bookmarks = soup.find("ol", {"class": "bookmark index group"})

        
        for bookm in bookmarks.find_all("li", {"class": ["bookmark", "index", "group"]}): # could use .find_all("li", {"role": "article"}) instead!!
            # this tmk doesnt actually find anything else than .find(ol) which created bookmarks!
            # doesnt matter though; 
            # for more coherecy: refactor to general purpose version 
            authors = []
            recommended = False
            workid = -1
            if bookm.h4 is not None:
                for a in bookm.h4.find_all("a"):
                    if "rel" in a.attrs.keys():
                        if "author" in a["rel"]:
                            authors.append(User(str(a.string), load=False))
                    elif a.attrs["href"].startswith("/works"):
                        workname = str(a.string)
                        workid = utils.workid_from_url(a["href"])

                # Get whether the bookmark is recommended
                for span in bookm.p.find_all("span"):
                    if "title" in span.attrs.keys():
                        if span["title"] == "Rec":
                            recommended = True

            
                if workid != -1:
                    new = Work(workid, load=False)
                    setattr(new, "title", workname)
                    setattr(new, "authors", authors)
                    setattr(new, "recommended", recommended)
                    if new not in self._bookmarks:
                        self._bookmarks.append(new)

    def _load_bookmarks_id(self, page=1):
        url = self._bookmarks_url.format(self.username, page)
        soup = self.request(url)
        #print(soup)
        
        '''
        #try later: general purpose version: 
        all_works_soup =soup.find("ol", {"class": ["index", "group"]})
        works_soup = all_works_soup.find_all("li", {"role": "article"})
        '''
        bookmarks = soup.find("ol", {"class": "bookmark index group"})

        
        for bookm in bookmarks.find_all("li", {"role": "article"}):
            workname = None
            workid = None
            for a in bookm.h4.find_all("a"):
                if a.attrs["href"].startswith("/works"):
                    workname = str(a.string)
                    workid = utils.workid_from_url(a["href"])
                    
            if workname != None and workid != None:
                self._bookmarks[workid]= workname
            
    #@cached_property
    def bookmarks(self):
        """Get the number of your bookmarks.
        Must be logged in to use.

        Returns:
            int: Number of bookmarks
        """

        url = self._bookmarks_url.format(self.username, 1)
        soup = self.request(url)
        div = soup.find("div", {"class": "bookmarks-index dashboard filtered region"})
        h2 = div.h2.text.split()
        return int(h2[4].replace(',', ''))
    
    def get_statistics(self, year=None):
        year = "All+Years" if year is None else str(year)
        url = f"https://archiveofourown.org/users/{self.username}/stats?year={year}"
        soup = self.request(url) 
        stats = {}
        dt = soup.find("dl", {"class": "statistics meta group"})
        if dt is not None:
            for field in dt.findAll("dt"):
                name = field.getText()[:-1].lower().replace(" ", "_")
                if field.next_sibling is not None and field.next_sibling.next_sibling is not None:
                    value = field.next_sibling.next_sibling.getText().replace(",", "")
                    if value.isdigit():
                        stats[name] = int(value)
        
        return stats

    @staticmethod
    def str_format(string):
        """Formats a given string

        Args:
            string (str): String to format

        Returns:
            str: Formatted string
        """

        return string.replace(",", "")

    # def get_marked_for_later(self, sleep=1, timeout_sleep=60):
    #     """
    #     Gets every marked for later work

    #     Arguments:
    #         sleep (int): The time to wait between page requests
    #         timeout_sleep (int): The time to wait after the rate limit is hit

    #     Returns:
    #         works (list): All marked for later works
    #     """
    #     pageRaw = self.request(f"https://archiveofourown.org/users/{self.username}/readings?page=1&show=to-read").find("ol", {"class": "pagination actions"}).find_all("li")
    #     maxPage = int(pageRaw[len(pageRaw)-2].text)
    #     works = []
    #     for page in range(maxPage):
    #         grabbed = False
    #         while grabbed == False:
    #             try:
    #                 workPage = self.request(f"https://archiveofourown.org/users/{self.username}/readings?page={page+1}&show=to-read")
    #                 worksRaw = workPage.find_all("li", {"role": "article"})
    #                 for work in worksRaw:
    #                     try:
    #                         workId = int(work.h4.a.get("href").split("/")[2])
    #                         works.append(Work(workId, session=self, load=False))
    #                     except AttributeError:
    #                         pass
    #                 grabbed = True
    #             except utils.HTTPError:
    #                 time.sleep(timeout_sleep)
    #         time.sleep(sleep)
    #     return works

    def _get_marked_for_later_pages(self):
        # pageRaw = self.request(f"https://archiveofourown.org/users/{self.username}/readings?page=1&show=to-read").find("ol", {"aria-label": "Pagination"}).find_all("li")
        # maxPage = int(pageRaw[len(pageRaw)-2].text)
        # return maxPage

        soup = self.request(f"https://archiveofourown.org/users/{self.username}/readings?page=1&show=to-read")
        pages = soup.find("ol",{"aria-label": "Pagination"})
        if pages is None:
            return 1
        n = 1
        for li in pages.findAll("li"):
            text = li.getText()
            if text.isdigit():
                n = int(text)
        return n

    
        
    def get_marked_for_later(self, hist_sleep=3, start_page=0, max_pages=None, timeout_sleep=60):
        """
        Gets every marked for later work

        Arguments:
            sleep (int): The time to wait between page requests
            timeout_sleep (int): The time to wait after the rate limit is hit

        Returns:
            works (list): All marked for later works
        """

        if self._marked_for_later is None:

          self._marked_for_later = {}
          self._marked_for_later_pages = self._get_marked_for_later_pages()

          for page in range(start_page, self._marked_for_later_pages):
                print(f"Processing page {page+1} of {self._marked_for_later_pages} pages.")
                #print(str(page))
                # If we are attempting to recover from errors then
                # catch and loop, otherwise just call and go
                if timeout_sleep is None:
                  self._load_marked_for_later(page=page+1)

                else:
                    loaded=False
                    while loaded == False:
                        try:
                            self._load_marked_for_later(page=page+1)
                            print(f"Read marked-for-later page {page+1}")
                            loaded = True

                        except utils.HTTPError:
                            print(f"Loading being rate limited, sleeping for {timeout_sleep} seconds")
                            time.sleep(timeout_sleep)


                  # Check for maximum history page load
                if max_pages is not None and page >= max_pages:
                    return self._marked_for_later 

                # Again attempt to avoid rate limiter, sleep for a few
                # seconds between page requests.
                if hist_sleep is not None and hist_sleep > 0:
                    print(f"Sleeping for {hist_sleep} seconds")
                    time.sleep(hist_sleep)
                    

        return self._marked_for_later 

    def _load_marked_for_later(self, page=1):   
        url = f"https://archiveofourown.org/users/{self.username}/readings?show=to-read&page={page}"
        workPage = self.request(url)
        worksRaw = workPage.find_all("li", {"role": "article"})
        #read_later = worksRaw.find("ol", {"class": "reading work index group"})
        '''
        #try later: general purpose version: 
        all_works_soup =soup.find("ol", {"class": ["index", "group"]})
        works_soup = all_works_soup.find_all("li", {"role": "article"})
        '''
        for item in worksRaw:
            # authors = []
            workname = None
            workid = None
            for a in item.h4.find_all("a"):
                if a.attrs["href"].startswith("/works"):
                    workname = str(a.string)
                    workid = utils.workid_from_url(a["href"])
                    
            if workname != None and workid != None:
                #new = Work(workid, load=False)
                #setattr(new, "title", workname)
                # setattr(new, "authors", authors)
                # hist_item = [ new, visited_num, visited_date ]
                # print(hist_item)
                #if new not in self._history:
                self._marked_for_later[workid]= workname


    def _get_bookmarked_series_pages(self):
        # pageRaw = self.request(f"https://archiveofourown.org/users/{self.username}/readings?page=1&show=to-read").find("ol", {"aria-label": "Pagination"}).find_all("li")
        # maxPage = int(pageRaw[len(pageRaw)-2].text)
        # return maxPage
        url = f"https://archiveofourown.org/bookmarks?bookmark_search%5Bbookmarkable_query%5D=bookmarkable_type%3A+Series&commit=Sort+and+Filter&user_id={self.username}&page=1"
        #soup = self.request(f"https://archiveofourown.org/bookmarks?bookmark_search[sort_column]=created_at&bookmark_search[other_tag_names]=&bookmark_search[other_bookmark_tag_names]=&bookmark_search[excluded_tag_names]=&bookmark_search[excluded_bookmark_tag_names]=&bookmark_search[bookmarkable_query]=bookmarkable_type%3A+Series&bookmark_search[bookmark_query]=&bookmark_search[language_id]=&bookmark_search[rec]=0&bookmark_search[with_notes]=0&commit=Sort+and+Filter&user_id={self.username}&page=1")
        soup = self.request(url)
        pages = soup.find("ol",{"aria-label": "Pagination"})
        if pages is None:
            pages = soup.find("ol",{"aria-label": "Pagination"})
        if pages is None:
            return 1
        n = 1
        for li in pages.findAll("li"):
            text = li.getText()
            if text.isdigit():
                n = int(text)
        return n

        
    def get_bookmarked_series(self, hist_sleep=3, start_page=0, max_pages=None, timeout_sleep=60):
        """
        Gets all bookmarked series 

        Arguments:
            sleep (int): The time to wait between page requests
            timeout_sleep (int): The time to wait after the rate limit is hit

        Returns:
            works (dict): all bookmarked Series
        """

        if self._series_bookmarks is None:

          self._series_bookmarks = {}
          self._bookmarked_series_pages = self._get_bookmarked_series_pages()

          for page in range(start_page, self._bookmarked_series_pages):
                print(f"Processing page {page+1} of {self._bookmarked_series_pages} pages.")
                #print(str(page))
                # If we are attempting to recover from errors then
                # catch and loop, otherwise just call and go
                if timeout_sleep is None:
                  self._load_bookmarked_series(page=page+1)

                else:
                    loaded=False
                    while loaded == False:
                        try:
                            self._load_bookmarked_series(page=page+1)
                            print(f"Read page {page+1}")
                            loaded = True

                        except utils.HTTPError:
                            print(f"Loading being rate limited, sleeping for {timeout_sleep} seconds")
                            time.sleep(timeout_sleep)


                  # Check for maximum history page load
                if max_pages is not None and page >= max_pages:
                    return self._series_bookmarks

                # Again attempt to avoid rate limiter, sleep for a few
                # seconds between page requests.
                if hist_sleep is not None and hist_sleep > 0:
                    print(f"Sleeping for {hist_sleep} seconds")
                    time.sleep(hist_sleep)
                    

        return self._series_bookmarks

    def _load_bookmarked_series(self, page=1):   

        
        #url = f"https://archiveofourown.org/bookmarks?bookmark_search[sort_column]=created_at&bookmark_search[other_tag_names]=&bookmark_search[other_bookmark_tag_names]=&bookmark_search[excluded_tag_names]=&bookmark_search[excluded_bookmark_tag_names]=&bookmark_search[bookmarkable_query]=bookmarkable_type%3A+Series&bookmark_search[bookmark_query]=&bookmark_search[language_id]=&bookmark_search[rec]=0&bookmark_search[with_notes]=0&commit=Sort+and+Filter&user_id={self.username}&page={page}"
        
        url = f"https://archiveofourown.org/bookmarks?bookmark_search%5Bbookmarkable_query%5D=bookmarkable_type%3A+Series&commit=Sort+and+Filter&user_id={self.username}&page={page}"
        workPage = self.request(url)
        worksRaw = workPage.find_all("li", {"role": "article"})
        #read_later = worksRaw.find("ol", {"class": "reading work index group"})
        '''
        #try later: general purpose version: 
        all_works_soup =soup.find("ol", {"class": ["index", "group"]})
        works_soup = all_works_soup.find_all("li", {"role": "article"})
        '''

        for item in worksRaw:
            # authors = []
            seriesname = None
            seriesid = None
            for a in item.h4.find_all("a"):
                if a.attrs["href"].startswith("/series"):
                    seriesname = str(a.string)
                    seriesid = utils.seriesid_from_url(a["href"])
                    
            if seriesname != None and seriesid != None:
                #new = Work(workid, load=False)
                #setattr(new, "title", workname)
                # setattr(new, "authors", authors)
                # hist_item = [ new, visited_num, visited_date ]
                # print(hist_item)
                #if new not in self._history:
                self._series_bookmarks[seriesid]= seriesname




