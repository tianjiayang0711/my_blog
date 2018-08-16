# -*- coding:utf-8 -*-
import re
import time
import json
import logging; logging.basicConfig(level=logging.INFO)
import hashlib
import markdown2
import asyncio
from apis import APIValueError, APIResourceNotFoundError, APIError, APIPermissionError ,Page
from aiohttp import web
from coroweb import get, post
from models import User, Blog, Comment, next_id
from config import configs

"""
url handlers
"""
COOKIE_NAME = 'myblogsession'
_COOKIE_KEY = configs.session.secret

_RE_EMAIL = re.compile(r'^[0-9a-z\.\_\-]+\@[a-z0-9\-\_]+(\.[a-z0-9\-\_]+){1,4}$')
_RE_SHA1 = re.compile(r'^[0-9a-f]{40}$')


def check_admin(request):
    if request.__user__ is None or not request.__user__.admin:
        raise APIPermissionError()


def get_page_index(page_str):
    p = 1
    try:
        p = int(page_str)
    except ValueError as e:
        pass
    if p < 1:
        p = 1
    return p


def user2cookie(user, max_age):
    """
    Generate cookie str by user(id-expires-sha1).
    """
    # build cookie string by: id-expires-sha1
    # 过期时间是创建时间+存活时间
    expires = str(int(time.time() + max_age))
    s = '%s-%s-%s-%s' % (user.id, user.passwd, expires, _COOKIE_KEY)
    # SHA1是一种单向算法，可以通过原始字符串计算出SHA1结果，但无法通过SHA1结果反推出原始字符串。
    L = [user.id, expires, hashlib.sha1(s.encode('utf-8')).hexdigest()]
    return '-'.join(L)


def text2html(text):
    # HTML转义字符
    # "		&quot;
    # & 	&amp;
    # < 	&lt;
    # > 	&gt;
    # 不断开空格	&nbsp;

    lines = map(lambda s: '<p>%s</p>' % s.replace('&', '%amp;').replace('<', '&alt;').replace('>', '&gt;'),
                filter(lambda s: s.strip() != '', text.split('\n')))
    return ''.join(lines)

@asyncio.coroutine
def cookie2user(cookie_str):
    """
    Parse cookie and load user if cookie is valid.
    """
    if not cookie_str:
        return None
    try:
        L = cookie_str.split('-')
        if len(L) != 3:
            return None
        uid, expires, sha1 = L
        if int(expires) < time.time():
            return None
        user = yield from User.find(uid)
        if user is None:
            return None
        s = '%s-%s-%s-%s' % (uid, user.passwd, expires, _COOKIE_KEY)
        if sha1 != hashlib.sha1(s.encode('utf-8')).hexdigest():
            logging.info('invalid sha1')
            return None
        user.passwd = '********'
        return user
    except Exception as e:
        logging.exception(e)
        return None


@post('/result')
@asyncio.coroutine
def handler_url_result(*, user_email, request):
    response = '<h1>你输入的邮箱是%s</h1>' % user_email
    return response


@get('/')
@asyncio.coroutine
def index(*, page='1'):
    # summary = "Try something new," \
    #           " lead to the new life."
    #
    # blogs = [
    #     Blog(id='1', name='Test Blog', summary=summary, created_at=time.time() - 120),
    #     Blog(id='2', name='Something New', summary=summary, created_at=time.time() - 3600),
    #     Blog(id='3', name='Learn Swift', summary=summary, created_at=time.time() - 7200)
    # ]
    # for blog in blogs:
    #     yield from blog.save()

    page_index = get_page_index(page)
    # 查找博客表里的条目数
    num = yield from Blog.findNumber('count(id)')
    # 没有条目则不显示
    if not num or num == 0:
        logging.info('the type of num is :%s' % type(num))
        blogs = []
    else:
        page = Page(num, page_index)
        # 根据计算出来的offset(取的初始条目index)和limit(取的条数)，来取出条目
        # 首页只显示前5篇文章
        blogs = yield from Blog.findAll(orderBy='created_at desc', limit=(0, 5))
    return {
        '__template__': 'blogs.html',
        'page': page,
        'blogs': blogs
        # '__template__'指定的模板文件是blogs.html，其他参数是传递给模板的数据
    }


@get('/register')
def register():
    return {
        "__template__": 'register.html'
    }


@post('/api/users')
@asyncio.coroutine
def api_register_user(*, email, name, passwd):
    if not name or not name.strip():
        raise APIValueError('name')
    if not email or not _RE_EMAIL.match(email):
        raise APIValueError('email')
    if not passwd or not _RE_SHA1.match(passwd):
        raise APIValueError('passwd')

    # 该邮箱是否已注册
    users = yield from User.findAll('email=?', [email])
    if len(users) > 0:
        raise APIError('register:failed', 'email', 'Email is already in use.')

    uid = next_id()
    # 数据库中存储的passwd是经过SHA1计算后的40位Hash字符串，所以服务器端并不知道用户的原始口令。
    # 传进来的 passwd:  passwd: CryptoJS.SHA1(email + ':' + this.password1).toString() 已经是 40 位hash字串（数据库中保存）
    sha1_passwd = '%s:%s' % (uid, passwd)
    user = User(id=uid, name=name.strip(), email=email,admin=True,passwd=hashlib.sha1(sha1_passwd.encode('utf-8')).hexdigest(),
                image='http://www.gravatar.com/avatar/%s?d=mm&s=120' % hashlib.md5(email.encode('utf-8')).hexdigest())
    yield from user.save()

    # make session cookie: 记录注册信息
    r = web.Response()
    r.set_cookie(COOKIE_NAME, user2cookie(user, 86400), max_age=86400, httponly=True)
    user.passwd = '********' # 同一显示
    r.content_type = 'application/json'
    r.body = json.dumps(user, ensure_ascii=False).encode('utf-8')
    return r


@get('/signin')
def signin():
    return {
        "__template__": 'signin.html'
    }


@post('/api/authenticate')
@asyncio.coroutine
def authenticate(*, email, passwd):
    if not email:
        raise APIValueError('email', 'Invalid email.')
    if not passwd:
        raise APIValueError('passwd', 'Invalid password.')
    users = yield from User.findAll('email=?', [email])
    if len(users) == 0:
        raise APIValueError('email', 'Email not exist.')
    user = users[0]

    # 在Python 3.x版本中，把'xxx'和u'xxx'统一成Unicode编码，即写不写前缀u都是一样的，
    # 而以字节形式表示的字符串则必须加上b前缀：b'xxx'。
    # sha1 = hashlib.sha1()
    # sha1.update(user.id.encode('utf-8'))
    # sha1.update(b':')
    # sha1.update(passwd.encode('utf-8'))

    # 检查密码 ： 与 注册时同一加密方法
    browser_sha1_passwd = '%s:%s' % (user.id, passwd)
    browser_sha1 = hashlib.sha1(browser_sha1_passwd.encode('utf-8'))
    if user.passwd != browser_sha1.hexdigest():
        raise APIValueError('passwd', 'Invalid password')

    # authenticate ok, set cookie
    r = web.Response()
    r.set_cookie(COOKIE_NAME, user2cookie(user, 86400), max_age=86400, httponly=True)
    user.passwd = "********"
    r.content_type = 'application/json'
    r.body = json.dumps(user, ensure_ascii=False).encode('utf-8')
    return r # 给 request


@get('/signout')
def signout(request):
    referer = request.headers.get('Referer')
    r = web.HTTPFound(referer or '/')
    # 清理掉cookie来退出账户
    r.set_cookie(COOKIE_NAME, '-deleted-', max_age=0, httponly=True)
    logging.info('user signed out.')
    return r


# -----------------------------------------管理用户----------------------------------------------
@get('/show_all_users')
@asyncio.coroutine
def show_all_users():
    users = yield from User.findAll()
    logging.info('to index...')
    return {
        '__template__': 'all_users.html',
        'users:': users
    }


@get('/api/users')
@asyncio.coroutine
def api_get_users(*, page='1'):
    logging.info('Api users is here!')
    page_index = get_page_index(page)
    # count为MySQL中的聚集函数，用于计算某列的行数
    # user_count代表了有多个用户id
    user_count = yield from User.findNumber('count(id)')
    p = Page(user_count, page_index)
    # 通过Page类来计算当前页的相关信息, 其实是数据库limit语句中的offset，limit
    if user_count == 0:
        return dict(page=p, users=())
    # page.offset表示从那一行开始检索，page.limit表示检索多少行
    users = yield from User.findAll(orderBy='created_at desc', limit=(p.offset, p.limit))

    for u in users:
        u.passwd = '*******'
    return dict(page=p, users=users)


@get('/manage/users')
def manage_users(*, page='1'):
    return {
        '__template__': 'manage_users.html',
        'page_index': get_page_index(page)
    }


# -----------------------------------------管理博客------------------------------------------------
@get('/manage/blogs/create')
def manage_create_blog():
    return {
        '__template__': 'manage_blog_edit.html',
        'id': '',
        'action': '/api/blogs'  # 对应HTML页面中VUE的action名字
    }


@get('/manage/blogs')
def manage_blogs(*, page='1'):
    return {
        '__template__': 'manage_blogs.html',
        'page_index': get_page_index(page)
    }


@post('/api/blogs')
@asyncio.coroutine
def api_create_blog(request, *, name, summary, content):
    check_admin(request)
    if not name or not name.strip():
        raise APIValueError('name', 'name cannot be empty.')
    if not summary or not summary.strip():
        raise APIValueError('summary', 'summary cannot be empty.')
    if not content or not content.strip():
        raise APIValueError('content', 'content cannot be empty.')
    blog = Blog(user_id=request.__user__.id, user_name=request.__user__.name, user_image=request.__user__.image,
                name=name.strip(), summary=summary.strip(), content=content.strip())
    yield from blog.save()
    # 返回一个dict,没有模板，会把信息直接显示出来
    return blog


@get('/api/blogs')
@asyncio.coroutine
def api_blogs(*, page='1'):
    page_index = get_page_index(page)
    blogs_count = yield from Blog.findNumber('count(id)')
    p = Page(blogs_count, page_index)
    if blogs_count == 0:
        return dict(page=p, blogs=())
    blogs = yield from Blog.findAll(orderBy='created_at desc', limit=(p.offset, p.limit))
    return dict(page=p, blogs=blogs)


@get('/blog/{id}')
@asyncio.coroutine
def get_blog(id):
    blog = yield from Blog.find(id)
    comments = yield from Comment.findAll('blog_id=?', [id], orderBy='created_at desc')
    for c in comments:
        c.html_content = text2html(c.content)
    blog.html_content = markdown2.markdown(blog.content)
    return {
        '__template__': 'blog.html',
        "blog": blog,
        'comments': comments
    }


@get('/api/blogs/{id}')
@asyncio.coroutine
def api_get_blog(*, id):
    blog = yield from Blog.find(id)
    return blog


@post('/api/blogs/delete/{id}')
@asyncio.coroutine
def api_delete_blog(id, request):
    logging.info('删除博客的ID为：%s' % id)
    check_admin(request)
    b = yield from Blog.find(id)
    if b is None:
        raise APIResourceNotFoundError('Blog')
        yield from b.remove()
    return dict(id=id)


@post('/api/blogs/modify')
@asyncio.coroutine
def api_modify_blog(request, *, id, name, summary, content):
    logging.info('修改的博客的ID为：%s' % id)

    if not name or not name.strip():
        raise APIValueError('name', 'name cannot be empty.')
    if not summary or not summary.strip():
        raise APIValueError('summary', 'summary cannot be empty.')
    if not content or not content.strip():
        raise APIValueError('content', 'content cannot be empty.')

    blog = yield from Blog.find(id)
    blog.name = name
    blog.summary = summary
    blog.content = content

    yield from blog.update()
    return blog


@get('/manage/blogs/modify/{id}')
def manage_modify_blog(id):
    return {
        '__template__': 'manage_blog_modify.html',
        'id': id,
        'action': '/api/blogs/modify'
    }


# ----------------------------------------评论管理-----------------------------------------
@get('/manage/')
@asyncio.coroutine
def manage():
    return 'redirect:/manage/comments'


@get('/manage/comments')
@asyncio.coroutine
def manage_commets(*, page='1'):
    return {
        '__template__': 'manage_comments.html',
        'page_index': get_page_index(page)
    }


@get('/api/comments')
@asyncio.coroutine
def api_comments(*, page='1'):
    page_index = get_page_index(page)
    num = yield from Comment.findNumber('count(id)')
    p = Page(num, page_index)
    if num == 0:
        return dict(page=p, comments=())
    comments = yield from Comment.findAll(orderBy='created_at desc', limit=(p.offset, p.limit))
    return dict(page=p, comments=comments)


@post('/api/blogs/{id}/comments')
@asyncio.coroutine
def api_create_comment(id, request, *, content):
    user = request.__user__
    if user is None:
        raise APIPermissionError('content')
    if not content or not content.strip():
        raise APIValueError('content')
    blog = yield from Blog.find(id)
    if blog is None:
        raise APIResourceNotFoundError('Blog')
    comment = Comment(blog_id=blog.id, user_id=user.id, user_name=user.name,
                      user_image=user.image, content=content.strip())
    yield from comment.save()
    return comment


@post('/api/comments/delete/{id}')
@asyncio.coroutine
def api_delete_comments(id, request):
    logging.info(id)
    check_admin(request)
    comment = yield from Comment.find(id)
    if comment is None:
        raise APIResourceNotFoundError('comment')
        yield from comment.remove()
    return dict(id=id)


















