from datetime import date
from datetime import datetime
from functools import cached_property
import datetime
import re
import time
from bs4 import BeautifulSoup


def id_user(work):  # work is one li-element
    ## getting most important metadata
    main = work['class']
    cleaned_list = [x for x in main if x not in ['work', 'blurb', 'group']]
    ids = [id.replace("work-", "") for id in main if id.startswith("work-")][0]
    users = [user.replace("user-", "") for user in main if user.startswith("user-")]
    return {"id": ids, "user_id": users}


def required_tags(work):
    req_tags_html = work.find("ul", class_="required-tags")
    # RATING
    rating_l = req_tags_html.find("span", class_="rating")['class']
    rating_l = [x for x in rating_l if x not in ['rating']]
    rating = [rating.replace("rating-", "") for rating in rating_l if rating.startswith("rating-")]
    # print(rating)

    # WARNING
    warning_l = req_tags_html.find("span", class_="warnings")['class']
    warning_l = [x for x in warning_l if x not in ['warning']]
    warning = [warning.replace("warning-", "") for warning in warning_l if warning.startswith("warning-")]
    # print(warning)

    # CATERGORY
    categegory_l = req_tags_html.find("span", class_="category")['class']
    categegory_l = [x for x in categegory_l if x not in ['category']]
    category = [category.replace("category-", "") for category in categegory_l if category.startswith("category-")]
    # print(category)

    # status
    status_l = req_tags_html.find("span", class_="iswip")['class']
    status_l = [x for x in status_l if x not in ['iswip']]
    status = [status for status in status_l]
    # print(status)

    return {"rating": rating, "warning": warning, "categories": category, "status": status}


def title_author(work):
    header = work.find("h4", class_="heading")
    title = header.find("a").text  # kinda risky vertraut auf title first <a>
    authors = [author.string for author in header.find_all("a", rel="author")]
    return {"title": title, "authors": authors}


def stats(work):
    stats = work.find("dl", class_="stats")
    props = {}
    for stat in stats.find_all("dd"):
        # print(stat.string)
        key = stat['class'][0]
        # print(key)
        props[key] = stat.text  # [a.get_text(strip=True) for a in stat.find_all("a")]

    chapters = props.get("chapters", "")
    props["nchapters"] = chapters.split("/")[0]
    props["expected_chapters"] = chapters.split("/")[-1]

    return props


def chaptercounts(metadict):
    chapters = metadict.get("chapters", "")
    return {
        "n_chapters": chapters.split("/")[0],
        "expected_chapters": chapters.split("/")[-1]
    }


def fand(work):
    header = work.find("h5", class_="fandoms")
    fandoms = [fandom.string for fandom in header.find_all("a", class_="tag")]
    return {"fandoms": fandoms}


def summary(work):
    summary = work.find("blockquote", class_="summary").text
    return {"summary": summary}


def tags(work):
    tags = work.find("ul", class_="tags")
    props = {}
    for tag in tags.find_all("li"):
        # print(stat.string)
        content = tag.text
        key = tag['class'][0]
        value = props.get(key)
        if not value:
            value = []
        value.append(content)

        props[key] = value
        # print(props)
    tags_list = props.get("freeforms", [])
    props["tags"] = tags_list
    props.pop("freeforms", None)
    return props


def some_date(work):
    some_date = work.find("p", class_="datetime").text
    if some_date:
        date_time_obj = datetime.strptime(some_date, '%d %b %Y')
        some_date = date_time_obj.strftime('%Y-%m-%d')
    return {"date_updated": some_date}


def series(work):
    series_return = []
    series_l = work.find("ul", class_="series")
    if series_l:
        for series in series_l.find_all("a"):
            series_id = series["href"].replace("/series/", "")
            # print(series.text)
            series_return.append(f"{series.text} ({series_id})")

    return {"series": series_return}
    # return work.find("p", class_="datetime").text


date_today = datetime.today().strftime('%Y-%m-%d')


def last_visited(work):
    visited_date = None
    visited_num = 0
    mfl = False
    status = None
    for viewed in work.find_all("h4", {"class": "viewed heading"}):
        # print(viewed)
        visited_num += 1
        data_string = str(viewed)
        date_str = re.search('<span>Last visited:</span> (\d{2} .+ \d{4})', data_string)
        if date_str is not None:
            raw_date = date_str.group(1)
            date_time_obj = datetime.strptime(date_str.group(1), '%d %b %Y')
            visited_date = date_time_obj.strftime('%Y-%m-%d')

        visited_str = re.search('Visited (\d+) times', data_string)
        if visited_str is not None:
            # print(visited_str)
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

    return {"last_visited": visited_date,
            "visits": visited_num, "mfl": mfl, "updatestatus": status
            }


def bookmark_info(work):
    bookmarked = False
    bm_date = None
    own_tags = []
    notes = None
    recommended = False
    bookmarked_by = None
    bookmarker = None
    # print(work)
    bookm = work.find("div", class_="user module group")
    if bookm:
        bookmarked = True
        # print(bookm)

        ## date of bookmark
        bm_date = bookm.find("p", class_="datetime").string
        bm_date = datetime.strptime(bm_date, '%d %b %Y')
        bm_date = bm_date.strftime('%Y-%m-%d')
        # print(bm_date)

        tags = bookm.find_all("a", class_="tag")
        if tags:
            for tag in tags:
                own_tags.append(tag.string)  # .rstrip('\n'))

        note = bookm.find("blockquote", class_="userstuff notes")
        if note:
            notes = note.text

        bookmarker = bookm.find("a").text

        if bookm.find("span", class_="rec"):
            recommended = True

        # Get whether the bookmark is recommended
        # for span in bookm.p.find_all("span"):
        #     print(span)
        #     if "title" in span.attrs.keys():
        #         if span["title"] == "Rec":
        #             recommended = True

    return {
        "bookmarked": bookmarked,
        "date_bookmarked": bm_date,
        "bookmarker_tags": own_tags,
        "notes": notes,
        "bookmarked_by": bookmarker,
        "recommended": recommended
    }


# ADD: Special: history

# ------------------------

def work_metadata_from_soup(work): #ie work = soup.find('li', role="article")
     work_metadata= id_user(work)
     work_id = work_metadata["id"]
     # add required tags
     work_metadata = work_metadata | required_tags(work)| title_author(work)| stats(work)| tags(work)| fand(work)| summary(work)| some_date(work)| series(work) | last_visited(work) | bookmark_info(work)
     return work_id, work_metadata







