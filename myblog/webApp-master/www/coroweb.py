#coding:utf-8

__author__ = 'Eric Lee'

import os, inspect
import logging; logging.basicConfig(level=logging.INFO)
import functools, asyncio
from urllib import parse
from aiohttp import web
from apis import APIError
import types

def get(path):
    '''
    define decorator @get(/path)
    '''
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kw):
            return func(*args, **kw)
        '''
        wrapper 属性，
        @get('path')
        def fn(*args, **kw):
            pass

        执行 fn(..) 最后一步就是执行wrapper(..),然后返回 func(..)
        '''
        wrapper.__method__ = 'GET'
        wrapper.__route__ = path
        return wrapper
    return decorator

def post(path):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kw):
            return func(*args, **kw)
        wrapper.__method__ = 'POST'
        wrapper.__route__ = path
        return wrapper
    return decorator

# --- 使用inspect模块中的signature方法来获取函数的参数，实现一些复用功能--
# inspect.Parameter 的类型有5种：
# POSITIONAL_ONLY		只能是位置参数
# KEYWORD_ONLY			关键字参数且提供了key
# VAR_POSITIONAL		相当于是 *args
# VAR_KEYWORD			相当于是 **kw
# POSITIONAL_OR_KEYWORD	可以是位置参数也可以是关键字参数
def get_required_kw_args(fn):
    args = []
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        #如果url处理函数需要传入关键字参数，且默认是空的话，获取这个key
        # fn(a,b='') -->b 符合要求
        if param.kind == inspect.Parameter.KEYWORD_ONLY and param.default == inspect.Parameter.empty:
            args.append(name)
    return tuple(args)

def get_named_kw_args(fn):
    args = []
    params = inspect.signature(fn).parameters
    # 如果url处理函数需要传入关键字参数，获取这个key
    # fn(a='default',b=None, c='') a,b,c 都可以获取
    for name, param in params.items():
        if param.kind == inspect.Parameter.KEYWORD_ONLY:
            args.append(name)
    return tuple(args)

def has_named_kw_args(fn):
    params = inspect.signature(fn).parameters
    #判断是否有关键字参数
    for name, param in params.items():
        if param.kind == inspect.Parameter.KEYWORD_ONLY:
            return True

def has_var_kw_arg(fn):
    params = inspect.signature(fn).parameters
    # 判断是否有关键字变长参数，VAR_KEYWORD对应**kw
    for name, param in params.items():
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            return True

def has_requset_arg(fn):
    sig = inspect.signature(fn)
    params = sig.parameters
    found = False
    # 判断是否存在 request 参数并且位于所有参数后
    # fn(a, b='', *args, **kw, request)
    for name, param in params.items():
        if name == 'request' or name == 're' or name == 'r':
            found = True
            continue
        # 找到 request 并且下一个参数什么都不是（就是没有参数），跳过 raise
        if found and (param.kind != inspect.Parameter.VAR_KEYWORD and param.kind != inspect.Parameter.VAR_POSITIONAL and param.kind != inspect.Parameter.KEYWORD_ONLY):
            raise ValueError('request paramter must be the last named parameter in function %s %s'%(fn.__name__, str(sig)))
    return found

# RequestHandler目的就是从URL处理函数（如handlers.index）中分析其需要接收的参数，然后从web.request对象中获取必要的参数，
# 在后面调用URL处理函数就可以进入这里，然后把结果转换为web.Response对象，这样，就完全符合aiohttp框架的要求
class RequestHandler(object):
    # app, 框架的主函数
    # fn: url 处理函数
    def __init__(self, app, fn):
        self._app = app
        self._func = fn
        self._has_request_arg = has_requset_arg(fn)
        self._has_var_kw_arg = has_var_kw_arg(fn)
        self._has_named_kw_args = has_named_kw_args(fn)
        self._named_kw_args = get_named_kw_args(fn)
        self._required_kw_args = get_required_kw_args(fn)

    # 1.定义kw对象，用于保存参数
    # 2.判断URL处理函数是否存在参数，如果存在则根据是POST还是GET方法将request请求内容保存到kw
    # 3.如果kw为空(说明request没有请求内容)，则将match_info列表里面的资源映射表赋值给kw；如果不为空则把命名关键字参数的内容fn（name=value）给kw
    # 4.完善_has_request_arg和_required_kw_args属性
    @asyncio.coroutine
    def __call__(self, request):
        kw = None
        # 有 **kw / name=value / name=''
        if self._has_var_kw_arg or self._has_named_kw_args or self._required_kw_args:
            if request.method == 'POST': # wrapper._method_
                if not request.content_type:
                    return web.HTTPBadRequest('Missing Content-Type')
                ct = request.content_type.lower()
                if ct.startswith('application/json'):
                    params = yield from request.json() #从json数组获取参数
                    if not isinstance(params, dict):
                        return web.HTTPBadRequest('JSON body must be object')
                    kw = params
                elif ct.startswith('application/x-www-form-urlencoded') or ct.startswith('multipart/form-data'):
                    params = yield from request.post() # k-v?
                    kw = dict(**params)
                else:
                    return web.HTTPBadRequest('Unsupported Content-Type: %s'%request.content_type)
            if request.method == 'GET':
                qs = request.query_string
                if qs:
                    kw = dict()
                    # get url ?后面的键值对
                    '''
                    qs = 'first=f,s&second=s'
                    parse.parse_qs(qs,True).items()
                    >>> dict([('first', ['f,s',]),('second', ['s',])])
                    '''
                    for k, v in parse.parse_qs(qs, True).items():
                        kw[k] = v[0] # v : ['f,s',]
        if kw is None:
            # request为空或者 url处理函数没有参数，直接从 match_info 获取
            '''
            def hello(request):
                text = '<h1>hello, %s!</h1>' % request.match_info['name']
                return web.Response()
            app.router.add_route('GET', '/hello/{name}', hello)
           '''
            kw = dict(**request.match_info)
        else:
            # 没有 **kw 参数只有 k=v
            if not self._has_var_kw_arg and self._named_kw_args:
                copy = dict()
                for name in self._named_kw_args:
                    if name in kw:
                        copy[name] = kw[name] #保持已有的值
                kw = copy
            for k, v in request.match_info.items():
                if k in kw: # check named arg: 检查关键字参数的名字是否和match_info中的重复
                    logging.info('Duplicate arg name in named arg and kw args: %s' % k)
                kw[k] = v
        if self._has_request_arg:
            kw['request'] = request #把 request 传进fn, 可能为空

        #检查是否有关键字参数并且放进了kw。且初始值为empty
        if self._required_kw_args:
            for name in self._required_kw_args:
                if not name in kw:
                    return web.HTTPBadRequest('Missing argument: %s '% name)
        logging.info('Call with args : %s'% str(kw))
        try:
            r = yield from self._func(**kw)
            return r
        except APIError as e:
            return dict(error=e.error, data=e.data, message=e.message)

# 添加 css 等静态文件路径
# static目录与本文件在同一级别目录下
def add_static(app):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
    app.router.add_static('/static/', path)
    logging.info('add static %s => %s' % ('/static/', path))

# 注册fn 成为真正的url处理函数 传递访问方法和路径进去
def add_route(app, fn):
    method = getattr(fn, '__method__', None)
    path = getattr(fn, '__route__', None)
    if path is None or method is None:
        raise ValueError('@get or @post not defined in %s.' % str(fn))
    if not asyncio.iscoroutinefunction(fn)  and not inspect.isgeneratorfunction(fn):
        fn = asyncio.coroutine(fn)
    logging.info('add route %s %s => %s(%s)' % (method, path, fn.__name__, ','.join(inspect.signature(fn).parameters.keys())))
    # 第三个参数是个函数，__call__()，类实例
    app.router.add_route(method, path, RequestHandler(app, fn))

# 批量添加
# rfind 来判断添加是： paths or paths.get
def add_routes(app, module_name):
    n = module_name.rfind('.')
    if n == (-1):
        # __import__ 作用同import语句，但__import__是一个函数，并且只接收字符串作为参数,
        # 其实import语句就是调用这个函数进行导入工作的, 其返回值是对应导入模块的引用
        # __import__('os',globals(),locals(),['path','pip']) ,等价于from os import path, pip
        mod = __import__(module_name, globals(), locals())
    else:
        name = module_name[n+1:] # 获取最后的模块
        # 导入 . 后面的模块
        mod = getattr(__import__(module_name[:n], globals(), locals(), [name]), name)
    for attr in dir(mod):
        if attr.startswith('_'): #私有属性
            continue
        fn = getattr(mod, attr)  #获取那些非私有属性 (函数块)
    #if callable(fn):
        #method = getattr(fn, '__method__', None) # 函数属性
        #path = getattr(fn, '__route__', None)
        #if method and path:
            #add_route(app, fn)
        if isinstance(fn,types.FunctionType):
            logging.info('hanlders function name is : %s' % fn)
            has_method = hasattr(fn, "__method__")
            has_path = hasattr(fn, "__route__")
            if has_method and has_path:
                logging.info('The func is call')
                add_route(app, fn)


