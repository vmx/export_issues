#!/usr/bin/env python3
"""
SPDX-License-Identifier: MIT

This script is based on Ryan Eberhardt work:
https://gist.github.com/reberhardt7/bf197865297a95b5ac3d

I modified it to fit my needs and released it unter the MIT License (with
permission).

This script uses Github's API V3 with a Token to export issues from
a repository. The script saves a json file with all of the information from the
API for issues, comments, and events (on the issues), downloads all of the
images attached to issues, and generates a markdown file that can be rendered
into a basic HTML page crudely mimicking Github's issue page.

In the end, you'll be left with a folder containing a raw .json file (which you
can use to extract information for your needs, or to import it somewhere else),
a .md (markdown) file, in addition to any image files referenced in issues.

To use the script, set the TOKEN and REPO variables below. You
will need the requests library, easily installed via pip or setuptools ("pip
install requests" or "easy_install requests").

The script is also somewhat modular, and functions can be imported by other
scripts.
"""

TOKEN = 'somegithubtoken'
REPO = 'someusername/somerepo'  # username/repo
ISSUE = None # Can be any issue number
# The folder to download issue data to
OUTPUT_FOLDER = '{}_issues'.format(REPO.replace('/', '_'))

import os
import re
import requests
import json
import base64
from collections import defaultdict

def load_all_resource(url, token):
    """
    Downloads JSON from an API URL. Github paginates when many items are
    present; if a requested URL has multiple pages, this function will request
    all the pages and concatenate the results.
    """
    print(url)
    headers = {
        'Accept': 'application/vnd.github.squirrel-girl-preview+json',
        'Authorization': 'token ' + token,
    }
    r = requests.get(url, headers=headers)
    if not r.ok:
        raise Exception('Github returned status code {} ({}) when loading {}. Check that '
                        'your username, password, and repo name are correct.'.format(r.status_code, r.reason, url))
    data = r.json()
    # Load data from the next pages, if any
    if 'link' in r.headers:
        pages = {rel: url for url, rel in re.findall(r'<(.*?)>;\s+rel=\"(.*?)\"', r.headers['link'])}
        print(pages)
        if 'next' in pages:
            data.extend(load_all_resource(pages['next'], token))
    return data

def get_json(token, repo, issue = None):
    """
    Downloads all of the JSON for all of the issues in a repository. Also
    retrieves the comments and events for each issue, and saves those in the
    'comments' and 'events' attributes in the dictionary for each issue.
    """
    if issue is not None:
        data = [
            load_all_resource(
                f'https://api.github.com/repos/{repo}/issues/{issue}',
                token=token)]
    else:
        data = load_all_resource(f'https://api.github.com/repos/{repo}/issues?state=all',
                                 token=token)
    # Load the comments and events on each issue
    for issue in data:
        print('#{}'.format(issue['number']))
        issue['reactions'] = load_all_resource(
            f'https://api.github.com/repos/{repo}/issues/{issue["number"]}/reactions',
            token=token)
        issue['comments'] = load_all_resource(issue['comments_url'],
                                              token=token)
        for comment in issue['comments']:
            if comment['reactions']['total_count'] > 0:
                comment['reactions_detailed'] = load_all_resource(
                    comment['reactions']['url'],
                    token=token)
        issue['events'] = load_all_resource(issue['events_url'], token=token)
        # If it is a pull request, also extract the source files and review
        # comments
        if 'pull_request' in issue:
            issue['reviews'] = load_all_resource(
                f'https://api.github.com/repos/{repo}/pulls/{issue["number"]}/reviews',
                token=token)
            # Review comments don't have a `created_at` value. Copy the
            # `submitted_at` value, so that further processing is more uniform
            for review in issue['reviews']:
                review['created_at'] = review['submitted_at']
            issue['review_comments'] = load_all_resource(
                f'https://api.github.com/repos/{repo}/pulls/{issue["number"]}/comments',
                token=token)
            issue['files'] = load_all_resource(
                f'https://api.github.com/repos/{repo}/pulls/{issue["number"]}/files',
                token=token)
            for file_ in issue['files']:
                file_['contents']= load_all_resource(
                    file_['contents_url'],
                    token=token)
    return data

def download_embedded_images(json_data, folder):
    """
    Downloads all of the images attached to issues for the repository.
    """
    json_str = json.dumps(json_data)
    for subdomain, path in re.findall(r'[\("]https:\/\/(cloud|user-images).githubusercontent.com\/(.*?)[\)"]', json_str):
        img_url = f'https://{subdomain}.githubusercontent.com/{path}'
        response = requests.get(img_url, stream=True)
        if not response.ok:
            raise Exception('Got a bad response while download the embedded image from {}! {} {}'.format(img_url, response.status_code, response.reason))
        filename = base64.b64encode(path.encode('utf-8')).decode('ascii') + '.' + path.rsplit('.', 1)[-1]
        with open(os.path.join(folder, filename), 'wb') as f:
            for block in response.iter_content(1024):
                if not block:
                    break
                f.write(block)

def mkdown_h(text, level, link=None):
    """
    Generates the markdown syntax for a header of a certain level.
    """
    if level == 1:
        return '\n' + ('<a name="{}"></a>'.format(link) if link else '') + text + '\n' \
                + '='*len(text)
    elif level == 2:
        return '\n' + ('<a name="{}"></a>'.format(link) if link else '') + text + '\n' \
                + '-'*len(text)
    else:
        return '\n' + '#'*level + ' ' + ('<a name="{}"></a>'.format(link) if link else '') + text

def mkdown_p(text):
    """
    Generates the markdown syntax for a paragraph.
    """
    return '\n'.join([line.strip() for line in text.splitlines()]) + '\n'

def mkdown_hr():
    """
    Generates the markdown syntax for a horizontal rule.
    """
    return '\n---'

def mkdown_blockquote(text):
    """
    Generates the markdown syntax for a blockquote.
    """
    return '\n'.join([f'> {line.strip()}' for line in text.splitlines()])

def build_markdown(repo, data):
    """
    Generates the markdown for a repository's issue page. The resulting markdown
    is a crude-but-functional mimicry of Github's issues.
    """
    lines = []
    if ISSUE is None:
        lines.append(mkdown_h('{} Issues'.format(repo), 1))
        for issue in sorted(data, key=lambda x: x['number']):
            lines.append('* [{1}: {0}](#{1})'.format(issue['title'], issue['number']))
            lines.append('')
    for issue in sorted(data, key=lambda x: x['number']):
        link = None
        if ISSUE is None:
            link = issue['number']
        lines.append(mkdown_h('#{}: {} ({})'.format(issue['number'], issue['title'], issue['state']), 2, link=link))
        closed_string = ', closed {}'.format(issue['closed_at']) if issue['closed_at'] else ''
        lines.append(mkdown_p('Opened {} by {}'.format(issue['created_at'], issue['user']['login']) + closed_string))
        lines.append(mkdown_p(issue['body']))

        # If it is a Pull Request, then ouput all markdown files with review
        # comments
        if 'pull_request' in issue:
            lines.append(mkdown_h('Files', 2))
            for file_ in issue['files']:
                if file_['contents']['name'].endswith('.md'):
                    lines.append(mkdown_p(f"`{file_['contents']['path']}`"))
                    contents = base64.b64decode(
                        file_['contents']['content']
                    ).decode('utf-8')

                    # A dict where the key is the line and the value is a list
                    # of comments sorted chronologically starting with the
                    # oldest
                    comments = defaultdict(list)
                    for comment in issue['review_comments']:
                        # Only look into comments of the current file
                        if comment['path'] != file_['contents']['path']:
                            continue

                        if comment['line'] is not None:
                            comments[comment['line']].append(comment)

                    # Contains the current code block opening line in case
                    # there was one
                    codeblock = None
                    for number, line in enumerate(contents.splitlines(), 1):
                        if line.startswith('```'):
                            if codeblock is None:
                                codeblock = line
                            else:
                                codeblock = None
                        lines.append(line)
                        if number in comments:
                            # Close current code block in order to output
                            # correctly formatted comments
                            if codeblock is not None:
                                lines.append('```')
                            for comment in comments[number]:
                                lines.append(mkdown_blockquote(mkdown_hr()))
                                lines.append(mkdown_blockquote(
                                    mkdown_h(
                                        '({}) {}:'.format(
                                            comment['created_at'],
                                            comment['user']['login']),
                                        4)))
                                lines.append(mkdown_blockquote(
                                    comment['body']))
                            # Open the code block again
                            if codeblock is not None:
                                lines.append(codeblock)
                    lines.append(mkdown_hr())

        lines.append(mkdown_h('Comments', 2))

        is_first_item = True
        for item in sorted(issue['comments']+issue['events']+issue['reviews'], key=lambda x: x['created_at']):
            if 'body' in item and item['body'] == '':
                continue

            items = []
            if 'user' in item:
                # It's a comment
                items.append(mkdown_h('({}) {}:'.format(item['created_at'], item['user']['login']), 4))
                items.append(mkdown_p(item['body']))
            elif 'event' in item and item['event'] == 'labeled':
                # It's a "labeled" event
                items.append(mkdown_h('({}) Labeled "{}"'.format(item['created_at'], item['label']['name']), 4))
            elif 'event' in item and item['event'] == 'assigned':
                # It's an "assigned" event
                items.append(mkdown_h('({}) Assigned to {}'.format(item['created_at'], item['assignee']['login']), 4))
            elif 'event' in item and item['event'] == 'referenced':
                # It's a "referenced" event
                items.append(mkdown_h('({}) Referenced by {} in commit {}'.format(item['created_at'], item['actor']['login'], item['commit_id']), 4))
            elif 'event' in item and item['event'] == 'closed':
                # It's a "closed" event
                items.append(mkdown_h('({}) Closed by {}'.format(item['created_at'], item['actor']['login']), 4))
            elif 'event' in item and item['event'] == 'reopened':
                # It's a "reopened" event
                items.append(mkdown_h('({}) Reopened by {}'.format(item['created_at'], item['actor']['login']), 4))

            # Don't put a horizontal rule before the first item
            if items:
                if is_first_item:
                    is_first_item = False
                else:
                    lines.append(mkdown_hr())

            lines.extend(items)

    return '\n'.join(lines)

if __name__ == '__main__':
    if not os.path.exists(OUTPUT_FOLDER):
        os.makedirs(OUTPUT_FOLDER)
    print('\033[32m' + 'Downloading issues...' + '\033[0m')
    issues = get_json(TOKEN, REPO, ISSUE)
    print('\033[32m' + 'Downloading images attached to issues...' + '\033[0m')
    download_embedded_images(issues, OUTPUT_FOLDER)
    print('\033[32m' + 'Saving JSON...' + '\033[0m')
    filename = 'issues'
    if ISSUE is not None:
        filename = f'{ISSUE}'
    with open(os.path.join(OUTPUT_FOLDER, f'{filename}.json'), 'w', encoding='utf-8') as f:
        json.dump(issues, f, indent=4)
    print('\033[32m' + 'Saving Markdown...' + '\033[0m')
    markdown = build_markdown(REPO, issues)
    with open(os.path.join(OUTPUT_FOLDER, f'{filename}.md'), 'w', encoding='utf-8') as f:
        f.write(markdown)
