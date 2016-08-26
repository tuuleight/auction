import bcrypt
from bson import ObjectId
import datetime
import concurrent.futures
import os.path
import re
import tornado.ioloop
import tornado.web
import tornado.httpserver
import pymongo

from tornado.concurrent import Future
from tornado import gen
from tornado.options import define, options, parse_command_line

define('port', default=8888, help='run on the given port', type=int)
define('debug', default=True, help='run in debug mode')

executor = concurrent.futures.ThreadPoolExecutor()


class Application(tornado.web.Application):
    def __init__(self):
        handlers = [
            (r'/', HomeHandler),
            (r'/auction/([^/]+)', AuctionHandler),
            (r'/(\w+)', ProfileHandler),
            (r'/new', NewHandler),
            (r'/auth/create', AuthCreateHandler),
            (r'/auth/login', AuthLoginHandler),
            (r'/auth/logout', AuthLogoutHandler),
        ]
        settings = dict(
            template_path=os.path.join(os.path.dirname(__file__), 'templates'),
            static_path=os.path.join(os.path.dirname(__file__), 'static'),
            xsrf_cookies=True,
            cookie_secret='WZqTEnR8fHAYTCCo23rZBCzJu85MxFQn8rz3a3aCZ5gCbFQtN5',
            debug=options.debug,
        )
        super(Application, self).__init__(handlers, **settings)
        client = pymongo.MongoClient('localhost', 27017)
        self.db = client.auction_database


class BaseHandler(tornado.web.RequestHandler):
    def db(self):
        return self.application.db

    def get_current_user(self):
        user_id = self.get_secure_cookie('auction_user')
        if not user_id:
            return None
        return user_id

    def does_author_exist(self, username):
        return bool(self.db().users.find_one({'username': username}))


class HomeHandler(BaseHandler):
    def get(self):
        auction = self.db().auctions.find().sort('start_date',
                                                 pymongo.DESCENDING)
        if not auction:
            self.write('No auctions yet. Feel free to register and add one!')

        self.render('index.html', auction=auction)


class AuctionHandler(BaseHandler):
    def get(self, slug):
        auction = self.db().auctions.find_one({'_id': ObjectId(slug)})
        offer = self.db().offers.find_one({'auction_id': ObjectId(slug)})
        if not auction:
            raise tornado.web.HTTPError(404)
        self.render('auction_page.html', auction=auction, offer=offer)


class ProfileHandler(BaseHandler):
    @tornado.web.authenticated
    def get(self, username):
        if username == self.current_user.decode('utf-8'):
            user_auctions = self.db().auctions.find({'username': username})
            u_auction = user_auctions.sort('start_date', pymongo.DESCENDING)
            user_offers = self.db().offers.find({'username': username})
            u_offer = user_offers.sort('datetime', pymongo.DESCENDING)
            self.render('profile.html', u_auction=u_auction, u_offer=u_offer)
        else:
            self.write('Sorry, restricted access')


class NewHandler(BaseHandler):
    @tornado.web.authenticated
    def get(self):
        self.render('new.html')

    @tornado.web.authenticated
    def post(self):
        name = self.get_argument('name')
        description = self.get_argument('description')
        price_min = self.get_argument('price')
        end_date = self.get_argument('end_date')

        new_auction = {
            'username': self.current_user,
            'name': name,
            'description': description,
            'price_min': price_min,
            'start_date': datetime.datetime.now(),
            'end_date': end_date
        }

        self.db().auctions.insert_one(new_auction)
        self.redirect('/')


class AuthCreateHandler(BaseHandler):
    def get(self):
        self.render('create_user.html')

    @gen.coroutine
    def post(self):
        username = self.get_argument('username')
        if self.does_author_exist(username):
            raise tornado.web.HTTPError(400, 'user already created')

        hashed_password = yield executor.submit(
            bcrypt.hashpw, tornado.escape.utf8(self.get_argument('password')),
            bcrypt.gensalt())

        user = {'username': username, 'password': hashed_password}
        self.db().users.save(user)
        self.set_secure_cookie('auction_user', username)
        self.redirect(self.get_argument('next', '/'))


class AuthLoginHandler(BaseHandler):
    def get(self):
        self.render('login.html')

    @gen.coroutine
    def post(self):
        username = self.get_argument('username')
        if not self.does_author_exist(username):
            self.redirect('/auth/create')

        user = self.db().users.find_one({'username': username})

        hashed_password = yield executor.submit(
            bcrypt.hashpw,
            tornado.escape.utf8(self.get_argument('password')),
            tornado.escape.utf8(user['password'].decode('utf-8')))

        if hashed_password == user['password']:
            self.set_secure_cookie('auction_user', username)
            self.render('login.html')
        else:
            self.render('login.html', error='incorrect password')


class AuthLogoutHandler(BaseHandler):
    def get(self):
        self.clear_cookie('auction_user')
        self.redirect(self.get_argument('next', '/'))


def main():
    parse_command_line()
    http_server = tornado.httpserver.HTTPServer(Application())
    http_server.listen(options.port)
    tornado.ioloop.IOLoop.current().start()

if __name__ == '__main__':
    main()
