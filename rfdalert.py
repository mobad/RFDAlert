#!/usr/bin/python3

import sqlite3
import re
import datetime
import configparser
import os
import cloudscraper
from urllib.parse import urljoin
from subprocess import Popen, PIPE
import dateutil.parser
from bs4 import BeautifulSoup

config = configparser.ConfigParser()
config.read(["rfd.cfg", os.path.expanduser("~/.rfd.cfg")])
config = config["rfd"]

conn = sqlite3.connect(config["db_path"])
c = conn.cursor()

emails = [email.strip() for email in config["emails"].split(",")]

rfdUrl = "http://forums.redflagdeals.com"
rfdSections = [section.strip() for section in config["sections"].split(",")]

scraper = cloudscraper.create_scraper()

for section in rfdSections:
    content = scraper.get(urljoin(rfdUrl, section)).text
    soup = BeautifulSoup(content, "lxml")

    for thread in soup.findAll("li", {"class": "topic"}):
        # Get post date.
        firstPostSoup = thread.find("span", {"class": "first-post-time"})
        if not firstPostSoup:
            continue

        threadCreateDate = dateutil.parser.parse(firstPostSoup.string)
        rfdtime = threadCreateDate.replace(tzinfo=dateutil.tz.gettz("America/Toronto"))
        utctime = rfdtime.astimezone(dateutil.tz.tzutc())
        daysOld = (
            datetime.datetime.utcnow().replace(tzinfo=dateutil.tz.tzutc()) - utctime
        ).days + 1

        # Get post votes.
        voteSoup = thread.find("dl", {"class": "post_voting"})
        if not voteSoup:
            continue

        votesStr = re.sub("[^0-9-]", "", voteSoup["data-total"])
        votes = int(votesStr if votesStr != "" else 0)

        # Get number of comments.
        postSoup = thread.find("div", {"class": "posts"})
        if not postSoup:
            continue
        posts = int(re.sub("[^0-9]", "", postSoup.string))

        # Get title.
        titleSoup = thread.find("h3", {"class": "topictitle"})
        if not titleSoup:
            continue

        title = ""
        for part in titleSoup:
            if part.string is not None:
                title += part.string.strip() + " "
        title = title.strip()

        timeSensitiveDeal = any(
            needle in title.lower()
            for needle in ["inferno", "volcano", "lava", "error"]
        )

        if (
            not timeSensitiveDeal and votes < 5 * daysOld and posts < 10 * daysOld
        ) or votes < 0:
            continue

        link = urljoin(
            rfdUrl, titleSoup.find("a", {"class": "topic_title_link"})["href"]
        )

        # Check whether post is in the database.
        c.execute("""SELECT COUNT(*) FROM rfd WHERE url=?""", (link,))
        if c.fetchone()[0] > 0:
            continue

        print(title + " " + link + " " + str(posts) + " " + str(votes))

        # Fetch post contents
        threadContent = scraper.get(link).text
        threadSoup = BeautifulSoup(threadContent, "lxml")
        for elem in threadSoup.findAll(["script", "style"]):
            elem.extract()

        dealSoup = threadSoup.find("div", {"class": "post_content"})
        if not dealSoup:
            continue

        # Convert relative links to absolute links.
        for a in dealSoup.findAll("a", href=True):
            a["href"] = urljoin(rfdUrl, a["href"])
        args = [
            "mutt",
            "-e",
            "set content_type=text/html",
            "-s",
            str(posts) + "|" + str(votes) + ": " + title,
        ]
        args.extend(emails)
        p = Popen(args, stdin=PIPE)
        p.communicate(input=bytes('<a href="' + link + '"/a>' + str(dealSoup), "utf-8"))
        if p.returncode != 0:
            continue
        print(p.returncode)
        c.execute("""INSERT INTO rfd VALUES (?)""", (link,))
conn.commit()
conn.close()
