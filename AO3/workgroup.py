from datetime import date
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


from datetime import datetime


def id_user(work): # work is one li-element
    ## getting most important metadata
    main = work['class']
    cleaned_list = [x for x in main if x not in ['work', 'blurb', 'group']]
    ids = [id.replace("work-","") for id in main if id.startswith("work-")][0]
    users = [user.replace("user-","") for user in main if user.startswith("user-")]
    return {"id":ids, "user_id":users}


def required_tags(work): 
    req_tags_html = work.find("ul", class_="required-tags")
    # RATING
    rating_l = req_tags_html.find("span", class_ = "rating")['class']
    rating_l = [x for x in rating_l if x not in ['rating']]
    rating = [rating.replace("rating-","") for rating in rating_l if rating.startswith("rating-")]
    #print(rating)

    # WARNING
    warning_l = req_tags_html.find("span", class_ = "warnings")['class']
    warning_l = [x for x in warning_l if x not in ['warning']]
    warning = [warning.replace("warning-","") for warning in warning_l if warning.startswith("warning-")]
    #print(warning)

    # CATERGORY
    categegory_l = req_tags_html.find("span", class_ = "category")['class']
    categegory_l = [x for x in categegory_l if x not in ['category']]
    category = [category.replace("category-","") for category in categegory_l if category.startswith("category-")]
    #print(category)

    # status
    status_l = req_tags_html.find("span", class_ = "iswip")['class']
    status_l = [x for x in status_l if x not in ['iswip']]
    status = [status for status in status_l]
    #print(status)

    return {"rating": rating, "warning": warning, "categories": category, "status":status}


def title_author(work):
    header = work.find("h4", class_= "heading")
    title = header.find("a").text # kinda risky vertraut auf title first <a>
    authors = [author.string for author in header.find_all("a", rel= "author")]
    return {"title":title, "authors":authors}

def stats(work):
    stats = work.find("dl", class_= "stats")
    props = {}
    for stat in stats.find_all("dd"):
        #print(stat.string)
        key = stat['class'][0]
        #print(key)
        props[key] = stat.text #[a.get_text(strip=True) for a in stat.find_all("a")]

    chapters= props.get("chapters", "")
    props["nchapters"] = chapters.split("/")[0]
    props["expected_chapters"] =chapters.split("/")[-1]

    return props

def chaptercounts(metadict): 
    chapters= metadict.get("chapters", "")
    return {
            "n_chapters" : chapters.split("/")[0],
            "expected_chapters" : chapters.split("/")[-1]
    }


def fand(work):
    header = work.find("h5", class_= "fandoms")
    fandoms = [fandom.string for fandom in header.find_all("a", class_="tag")]
    return {"fandoms":fandoms}

def summary(work):
    summary = work.find("blockquote", class_= "summary").text
    return {"summary":summary}

def tags(work): 
    tags = work.find("ul", class_= "tags")
    props = {}
    for tag in tags.find_all("li"):
        #print(stat.string)
        content = tag.text
        key = tag['class'][0]
        value = props.get(key)
        if not value: 
            value = []
        value.append(content)

        props[key] = value
        # print(props)
    tags_list = props.get("freeforms",[])
    props["tags"] = tags_list
    props.pop("freeforms", None)
    return props

def some_date(work): 
    some_date=work.find("p", class_="datetime").text
    if some_date: 
        date_time_obj = datetime.strptime(some_date, '%d %b %Y')
        some_date = date_time_obj.strftime('%Y-%m-%d')
    return {"date_updated":some_date}

def series(work): 
    series_return = [] 
    series_l = work.find("ul", class_="series")
    if series_l: 
        for series in series_l.find_all("a"):
            series_id = series["href"].replace("/series/","")
            # print(series.text) 
            series_return.append(f"{series.text} ({series_id})")

    return {"series": series_return}
    #return work.find("p", class_="datetime").text

date_today = datetime.today().strftime('%Y-%m-%d')
def last_visited(work): 
    visited_date= None
    visited_num = 0
    mfl = False
    status = None 
    for viewed in work.find_all("h4", {"class": "viewed heading"}):
        #print(viewed)
        visited_num +=1
        data_string = str(viewed)
        date_str = re.search('<span>Last visited:</span> (\d{2} .+ \d{4})', data_string)
        if date_str is not None:
            raw_date = date_str.group(1)
            date_time_obj = datetime.strptime(date_str.group(1), '%d %b %Y')
            visited_date = date_time_obj.strftime('%Y-%m-%d')
    
        visited_str = re.search('Visited (\d+) times', data_string)
        if visited_str is not None:
            #print(visited_str)
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
        status = f"{status}_{date_today}"

    return {"last_visited":visited_date,
            "visits":visited_num, "mfl":mfl, "updatestatus":status
    }      


def bookmark_info(work):
    bookmarked=False
    bm_date = None 
    own_tags=[]
    notes=None
    recommended = False
    bookmarked_by = None
    bookmarker=None
    #print(work)
    bookm = work.find("div", class_="user module group")
    if bookm: 
        bookmarked=True
        #print(bookm)

        ## date of bookmark
        bm_date = bookm.find("p", class_="datetime").string
        bm_date = datetime.strptime(bm_date, '%d %b %Y')
        bm_date = bm_date.strftime('%Y-%m-%d')
        #print(bm_date)

        tags = bookm.find_all("a", class_="tag")
        if tags: 
            for tag in tags: 
                own_tags.append(tag.string) #.rstrip('\n'))

        
        note = bookm.find("blockquote", class_="userstuff notes")
        if note: 
            notes = note.text

        bookmarker= bookm.find("a").text

        if bookm.find("span", class_="rec"): 
            recommended = True

        # Get whether the bookmark is recommended
        # for span in bookm.p.find_all("span"):
        #     print(span)
        #     if "title" in span.attrs.keys():
        #         if span["title"] == "Rec":
        #             recommended = True


    return{
        "bookmarked":bookmarked,
        "date_bookmarked":bm_date,
        "bookmarker_tags": own_tags, 
        "notes":notes,
        "bookmarked_by":bookmarker, 
        "recommended": recommended
    }         
# ADD: Special: history 




class Workgroup:
    def __init__(self, url, session=None, load=True, filter = False):
        """Creates a new 'Work Group' object from a url

        Args:
            url (str): ao3-url for a group of works; can be user-work-page, search results etc; can also be series or collection url !!
            session (AO3.Session, optional): Session object. Defaults to None.
            load (bool, optional): If true, loaded on initialization. Defaults to True.

        Raises:
            utils.InvalidIdError: Invalid url
        """

        self._session = session
        #self._soup_start = None
        self._soup = None
        self.group_url = url
        self._work_ids = None
        self._pages = None
        #self._name = None
        self._filter = filter 

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
        self._pages = self.pages
        self._name = self.name()
        if "Error 404" in self._soup.text:
            raise utils.InvalidIdError("Cannot find page")

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

        heading = self._soup.find("h2", {"class": "heading"})
        return heading.text.strip()

    @cached_property
    def pages(self):
        pages = self._soup.find("ol", {"aria-label": "Pagination"})
        if pages is None:
            return 1
        n = 1
        for li in pages.find_all("li"):
            text = li.getText()
            if text.isdigit():
                n = int(text)

        if n > 10:
            print(f"WARNING: this group of works contains more than {(n-1)*20} items on {n} pages.")
        return n


    
    def get_work_ids(self, hist_sleep=3, start_page=0, max_pages=None, timeout_sleep=60):
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
