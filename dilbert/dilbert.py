#!/usr/bin/python3
# vim:ft=python:expandtab:sw=4:tw=140

import sys
from os import PathLike
from typing import Union, List, Generator, TextIO, overload
import re
import time
from pathlib import Path
import sqlite3
from datetime import date, datetime, timedelta
from http.client import HTTPResponse
from urllib import request, response, error
import lxml.html
import feedgenerator

if sys.version_info < (3, 7):
    print("This script requires Python version 3.7")
    sys.exit(1)

DEBUG = True

# note: inclusive counting
def _daterange(start_date: date, end_date: date) -> Generator[date, None, None]:
    for n in range(int((end_date - start_date).days) + 1):
        yield start_date + timedelta(days=n)


def _debug(*args) -> None:
    if DEBUG:
        print(args)
    return


class DilbertComic(object):
    def __init__(self, row: sqlite3.Row=None,
                       comic_id: int=None,
                       pubdate: date=None,
                       url: str=None,
                       filename: PathLike=None,
                       title: str=None,
                       updated: datetime=None,
                       width: int=None,
                       height: int=None) -> None:
        if row:
            self.id       = row['id']
            self.url      = row['url']
            self.filename = row['filename']
            self.title    = row['title']
            self.pubdate  = date.fromisoformat(row['pubdate'])  # type: ignore
            self.updated  = datetime.fromisoformat(row['updated'])  # type: ignore
            self.width    = row['width']
            self.height   = row['height']
        else:
            self.id       = comic_id
            self.pubdate  = pubdate
            self.url      = url
            self.filename = filename
            self.title    = title
            self.updated  = updated
            self.width    = width
            self.height   = height

        # fix empty titles on sundays
        if self.title == '':
            self.title = "-"

        _debug("Init comic {} for {}".format(self.url, self.pubdate))

    @overload
    def __getitem__(self, key: str) -> str:
        ...

    @overload  # noqa: F811
    def __getitem__(self, key: str) -> date:
        ...

    def __getitem__(self, key):  # noqa: F811
        return self.__dict__[key]

    def tag(self, baseurl: str='.') -> Union[str, date]:
        w = ''
        h = ''
        if self.width:
            w = 'width="{}"'.format(self.width)
        if self.height:
            h = 'height="{}"'.format(self.height)

        url = '{}/{}'.format(baseurl, self.filename)
        tag = '<img src="{}" alt="comic for {}" {} {}/>'.format(url, self.pubdate, w, h)
        return tag


class Dilbert(object):
    def __init__(self, basepath: PathLike, baseurl: str='.') -> None:
        self._basepath = Path(basepath)
        self.db = self.open_db()
        self.UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_9_3) AppleWebKit/537.36 (KHTML, like Gecko) ' \
                + 'Chrome/35.0.1916.4 7 Safari/537.36'
        self.baseurl = baseurl
        self.feedname = Path("dilbert.rss")
        _debug("Found baseurl {}".format(self.baseurl))

    def __del__(self):
        self.db.close()

    def open_db(self) -> sqlite3.Connection:
        db = Path(self._basepath, "dilbert.sqlite3")
        con = sqlite3.connect(db)  # type: ignore
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS `dilbert` (
                id       INTEGER  PRIMARY KEY AUTOINCREMENT,
                pubdate  DATE     NOT NULL,
                url      TEXT     NOT NULL,
                title    TEXT,
                filename TEXT     UNIQUE NOT NULL,
                width    INT,
                height   INT,
                updated  DATETIME DEFAULT(STRFTIME('%Y-%m-%d %H:%M:%f', 'NOW'))
            );
        """)
        con.commit()
        return con

    def fetch_url(self, url: str) -> HTTPResponse:
        req = request.Request(url, data=None, headers={'User-Agent': self.UA})
        res = request.urlopen(req)
        if isinstance(res, response.addinfourl):
            raise error.URLError("Got FTP handle instead of HTTP response")

        return res  # type: ignore

    # fetch most recent date present in database
    def latest_date_in_db(self) -> date:
        latest = None
        for row in self.db.execute("select `pubdate` from dilbert order by `pubdate` desc limit 1"):
            latest = date.fromisoformat(row['pubdate'])  # type: ignore
        _debug("Latest date found is {}".format(str(latest)))
        return latest  # type: ignore

    # fetch most recent date present in database
    def comics(self, num: int=10) -> List[DilbertComic]:
        _debug("Fetching {:d} latest comics from database".format(num))
        comics = list()
        for row in self.db.execute("select * from dilbert order by `pubdate` desc limit {:d}".format(num)):
            _debug("Found comic for {}".format(row['pubdate']))
            comics.append(DilbertComic(row=row))
        return comics

    def find_comic_by_pubdate(self, pubdate: date) -> DilbertComic:
        print("Fetching comic for {}".format(pubdate))
        _debug("Fetching comic for {}".format(pubdate))
        url = "http://dilbert.com/strip/{}".format(pubdate.isoformat())
        _debug("Fetching url `{}`".format(url))
        res = self.fetch_url(url)
        _debug("Status: {}".format(res.status))
        body = res.read()
        html = lxml.html.document_fromstring(body)
        el = html.xpath("//img[@class and contains(concat(' ', normalize-space(@class), ' '), ' img-comic ')]")[0]
        comic = DilbertComic(
            pubdate     = pubdate,
            url      = el.get('src'),
            title    = re.sub(' - .*$', '', el.get('alt')),
            filename = Path("{}.gif".format(pubdate.isoformat())),
            width    = el.get('width'),
            height   = el.get('height'),
        )
        return comic

    def download_comic(self, filename: str, url: str) -> None:
        filename_full = 'cartoons/{}'.format(filename)
        _debug("Downloading '{}' to '{}'".format(url, filename_full))
        res = self.fetch_url(url)
        _debug("Status: {}".format(res.status))
        _debug("Headers: {}".format(res.getheaders()))
        with open(filename_full, 'wb') as fd:
            fd.write(res.read())
        return

    def write_comic_to_db(self, comic: DilbertComic) -> None:
        cur = self.db.cursor()
        _debug("Adding record for {} to database".format(comic.pubdate))
        cur.execute(
            "insert into `dilbert` (pubdate,url,title,filename,width,height) values (?,?,?,?,?,?)",
            [str(comic[k]) for k in ('pubdate', 'url', 'title', 'filename', 'width', 'height')]
        )
        self.db.commit()
        return

    def update_comic_by_pubdate(self, pubdate: date) -> None:
        comic = self.find_comic_by_pubdate(pubdate)
        self.download_comic(comic.filename, comic.url)
        self.write_comic_to_db(comic)

    def update(self) -> None:
        start = self.latest_date_in_db()
        # default: 10 days ago
        if not start:
            start = date.today() - timedelta(days=10)

        start = start + timedelta(days=1)

        for pubdate in _daterange(start, date.today()):
            self.update_comic_by_pubdate(pubdate)
            time.sleep(1.2)
        return

    def feed(self) -> feedgenerator.SyndicationFeed:
        feed = feedgenerator.Atom1Feed(
            title="De dagelijke Dilbert",
            link="http://dilbert.com/",
            feed_url = "{}/{}".format(self.baseurl, self.feedname),
            description="Daily dilbert in a nice feed",
            language="en",
        )

        for comic in self.comics(10):
            _debug("Adding comic for {}".format(comic.pubdate))
            feed.add_item(
                title       = comic.title,
                author_name = "Scott Adams",
                link        = "http://dilbert.com/strip/{}".format(comic.pubdate),
                updateddate = comic.updated,
                pubdate     = datetime.combine(comic.pubdate, datetime.min.time()),
                description = comic.tag(baseurl = self.baseurl),
            )
        return feed

    def rss(self) -> str:
        return self.feed().writeString('UTF-8')

    def write_rss(self, fd: TextIO) -> None:
        return self.feed().write(fd, 'UTF-8')


if __name__ == "__main__":
    if len(sys.argv) == 2:
        baseurl = sys.argv[1]
    else:
        baseurl = "http://localhost"

    dilbert = Dilbert(basepath=".", baseurl=baseurl)
    dilbert.update()

    with open(dilbert.feedname, "w") as fd:
        dilbert.write_rss(fd)
