"""Structured GitHub operations; never accepts a shell, argv, file or header."""
import json
import re
from urllib.parse import urlsplit, parse_qsl
from typing import NoReturn

MAX_BODY = 512 * 1024
FIELDS = set('nameWithOwner number title state author updatedAt url baseRefName headRefName isDraft additions deletions changedFiles reviewDecision statusCheckRollup labels body createdAt comments name bucket link'.split())
REPO = r'[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9_.-]+'


def fail() -> NoReturn:
    raise ValueError('Unsupported GitHub operation')


def text(value, limit=1024):
    if not isinstance(value, str) or len(value) > limit or '\x00' in value:
        fail()
    return value


def compile_operation(op):
    if not isinstance(op, dict) or len(json.dumps(op, ensure_ascii=False).encode()) > MAX_BODY:
        fail()
    kind = op.get('operation')
    if kind == 'github.api':
        if set(op) - {'operation', 'path', 'method', 'body'}:
            fail()
        path = text(op.get('path'), 4096)
        method = op.get('method', 'GET')
        parsed = urlsplit(path)
        if (parsed.scheme or parsed.netloc or parsed.fragment or path.startswith('/')
                or '%' in parsed.path or '\\' in path or any(p in {'.', '..', ''} for p in parsed.path.split('/'))):
            fail()
        allowed = (parsed.path in {'user', 'graphql', 'search/issues'} or
                   re.fullmatch(r'repos/' + REPO + r'/(?:pulls|issues|commits|compare)(?:/[A-Za-z0-9_.-]+)*', parsed.path))
        if not allowed or method not in {'GET', 'POST', 'PATCH', 'PUT', 'DELETE'}:
            fail()
        body = op.get('body')
        if body is not None and not isinstance(body, dict):
            fail()
        if method == 'GET' and body is not None:
            fail()
        if parsed.path == 'graphql':
            if method != 'POST' or not body or set(body) - {'query', 'variables', 'operationName'}:
                fail()
            query = text(body.get('query'), 32768)
            # This seam is read-only GraphQL. Mutation support must be a named,
            # audited operation rather than an arbitrary GraphQL document.
            if re.search(r'\bmutation\b', query) or not re.match(r'\s*(?:query\b|\{)', query):
                fail()
        elif method != 'GET':
            if not re.fullmatch(r'repos/' + REPO + r'/(?:issues/[1-9][0-9]*/comments|pulls/[1-9][0-9]*/reviews)', parsed.path) or method != 'POST':
                fail()
            if not body or set(body) - {'body', 'event'}:
                fail()
            if 'body' in body:
                text(body['body'], 65536)
            if 'event' in body and body['event'] != 'APPROVE':
                fail()
        for key, value in parse_qsl(parsed.query, keep_blank_values=True):
            if key not in {'per_page', 'page', 'direction', 'sort', 'order', 'q', 'state'} or len(value) > 2000:
                fail()
        args = ['api', '--hostname', 'github.com', '--method', method, path]
        if body is not None:
            args += ['--input', '-']
        return args, body
    if kind not in {'repo.list', 'repo.view', 'pr.list', 'pr.view', 'pr.checks', 'pr.merge', 'pr.review', 'issue.list', 'issue.view', 'issue.close', 'issue.reopen'}:
        fail()
    allowed = {'operation'}
    if kind != 'repo.list':
        allowed.add('repo')
    action = kind.split('.')[1]
    if action in {'list', 'view', 'checks'}:
        allowed.add('fields')
    if action in {'view', 'checks', 'merge', 'review', 'close', 'reopen'} and not kind.startswith('repo.'):
        allowed.add('number')
    if action == 'list':
        allowed.add('limit')
        if not kind.startswith('repo.'):
            allowed.add('state')
        if kind == 'pr.list':
            allowed.add('head')
    if kind == 'pr.merge':
        allowed.update({'strategy', 'deleteBranch'})
    if set(op) - allowed:
        fail()
    command, action = kind.split('.')
    args = [command, action]
    repo = op.get('repo')
    if kind != 'repo.list':
        if not isinstance(repo, str) or not re.fullmatch(REPO, repo) or any(x in {'.', '..'} for x in repo.split('/')):
            fail()
        args += [repo] if kind == 'repo.view' else ['--repo', repo]
    if action in {'view', 'checks', 'merge', 'review', 'close', 'reopen'} and command != 'repo':
        number = str(op.get('number', ''))
        if not re.fullmatch(r'[1-9][0-9]{0,9}', number):
            fail()
        args.append(number)
    if 'fields' in op:
        fields = text(op['fields']).split(',')
        if not fields or any(f not in FIELDS for f in fields) or action in {'merge', 'review', 'close', 'reopen'}:
            fail()
        args += ['--json', ','.join(fields)]
    if action == 'list':
        limit = op.get('limit', 30)
        if type(limit) is not int or not 1 <= limit <= 120:
            fail()
        args += ['--limit', str(limit)]
        if 'state' in op:
            if op['state'] not in {'open', 'closed', 'merged', 'all'}:
                fail()
            args += ['--state', op['state']]
        if 'head' in op:
            args += ['--head', text(op['head'], 255)]
    if kind == 'pr.merge':
        strategy = op.get('strategy', 'merge')
        if strategy not in {'merge', 'squash', 'rebase'} or type(op.get('deleteBranch', False)) is not bool:
            fail()
        args += ['--' + strategy]
        if op.get('deleteBranch'):
            args.append('--delete-branch')
    if kind == 'pr.review':
        args.append('--approve')
    return args, None
