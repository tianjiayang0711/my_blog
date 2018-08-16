#coding:utf-8

__author__ = 'Eric Lee'
'''
Json API definition
'''

import json, logging, inspect, functools

class Page(object):
    """
    Page object for display pages.
    """
    def __init__(self, item_count, page_index=1, page_size=10):
        """
        Init pagination by item_count, page_index and page_size
        >>> p1 = Page(100,1)
        >>> p1.page_count
        10
        >>> p1.offset
        0
        >>> p1.limit
        10
        >>> p2 = Page(90, 9, 10)
        >>> p2.page_count
        9
        >>> p2.offset
        80
        >>> p2.limit
        10
        >>> p3 = Page(91, 10, 10)
        >>> p3.page_count
        10
        >>> p3.offset
        90
        >>> p3.limit
        10
        """
        # item_count 文章的总数
        # page_size 每页显示的文章数量
        # page_count 需要多少页将文章显示出来
        self.item_count = item_count
        self.page_size = page_size
        self.page_count = item_count // page_size + (1 if item_count % page_size > 0 else 0)
        if (item_count == 0) or (page_index > self.page_count):
            self.offset = 0
            self.limit = 0
            self.page_index = 1
        else:
            # page_index 待查看那一页
            self.page_index = page_index
            # 这一页前面有多少文章
            self.offset = self.page_size * (page_index - 1)
            # 本页的最后一项排序，满足：
            # 1. 可能不是第一页
            # 2. 最后一页不满
            self.limit = (item_count-self.offset) if (item_count-self.offset) < page_size else  self.offset + self.page_size
        self.has_next = self.page_index < self.page_count
        self.has_previous = self.page_index > 1

    def __str__(self):
        return 'item_count: %s, page_count: %s, page_index: %s, page_size: %s, offset:%s, limit:%s' \
                % (self.item_count, self.page_count, self.page_index, self.page_size, self.offset, self.limit)

    __repr__ = __str__ # 机器和人看到的一样 （print 调用__str__, python解析器回车调用__repr__）

class APIError(Exception):
    '''
    the base APIError which contains error(required), data(optional) and message(optional).
    '''
    def __init__(self, error, data='', message=''):
        super(APIError, self).__init__(message)
        self.error = error
        self.data  = data
        self.message = message

class APIValueError(APIError):
    '''
    Indicate the input value has error or invalid. The data specifies the error field of input form.
    '''
    def __init__(self, field, message=''):
        super(APIValueError, self).__init__('value:invalid', field, message)

class APIResourceNotFoundError(APIError):
    '''
    Indicate the resource was not found. The data specifies the resource name.
    '''
    def __init__(self, field, message=''):
        super(APIResourceNotFoundError, self).__init__('value:notfound', field, message)

class APIPermissionError(APIError):
    '''
    Indicate the api has no permission.
    '''
    def __init__(self, message=''):
        super(APIPermissionError, self).__init__('permission:forbidden', 'permission', message)