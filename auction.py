import bcrypt
from bson import ObjectId
import datetime
import concurrent.futures
import os.path
import tornado.ioloop
import tornado.web
import tornado.httpserver
import motor.motor_tornado

from tornado.concurrent import Future
from tornado import gen
from tornado.options import define, options, parse_command_line

define('port', default=8888, help='run on the given port', type=int)
define('debug', default=True, help='run in debug mode')

executor = concurrent.futures.ThreadPoolExecutor()
client = motor.motor_tornado.MotorClient()
db = client.auction_database


class Application(tornado.web.Application):
    def __init__(self):
        handlers = [
            (r'/', HomeHandler),
            (r'/auction/([^/]+)', AuctionHandler),
            (r'/(\w+)', ProfileHandler),
            (r'/create/new', NewHandler),
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


class BaseHandler(tornado.web.RequestHandler):
    def get_current_user(self):
        user_id = self.get_secure_cookie('auction_user')
        if not user_id:
            return None
        return user_id

    @gen.coroutine
    def does_user_exist(self, username):
        document = yield db.users.find_one({'username': username})
        return document

    @gen.coroutine
    def get_auctions(self):
        n = yield db.auctions.find().count()
        auctions = yield db.auctions.find().sort([('start_date',
                                                   -1)]).to_list(n)
        return auctions

    @gen.coroutine
    def get_offers(self, slug):
        n = yield db.offers.find({'auction_id': slug}).count()
        offers = yield db.offers.find({'auction_id': slug}).sort([(
            'price', -1)]).to_list(n)
        return offers

    @gen.coroutine
    def find_auctions(self, username):
        n = yield db.auctions.find({'username': username}).count()
        auctions = yield db.auctions.find({'username': username}).sort([(
            'start_date', -1)]).to_list(n)
        return auctions

    @gen.coroutine
    def find_offers(self, username):
        n = yield db.offers.find({'username': username}).count()
        offers = yield db.offers.find({'username': username}).sort([(
            'datetime', -1)]).to_list(n)
        return offers


class HomeHandler(BaseHandler):
    @gen.coroutine
    def get(self):
        auction = yield self.get_auctions()
        self.render('index.html', auction=auction)


class AuctionHandler(BaseHandler):
    @gen.coroutine
    def get(self, slug):
        auction = yield db.auctions.find_one({'_id': ObjectId(slug)})
        offer = yield self.get_offers(slug)
        if not auction:
            raise tornado.web.HTTPError(404)
        self.render('auction_page.html', auction=auction, offer=offer)

    @tornado.web.authenticated
    @gen.coroutine
    def post(self, slug):
        auction = yield db.auctions.find_one({'_id': ObjectId(slug)})
        auction_author = auction['username']

        # Unable for auction creator to post offer
        if self.current_user.decode('utf-8') == auction_author:
            self.write('Your own auction')
        else:
            offer_price = int(self.get_argument('price'))

            if offer_price < auction['price_min']:
                self.write('Price lower than minimum for that auction. Go '
                           'back and make higher offer')
            else:
                offer = {
                    'username': self.current_user.decode('utf-8'),
                    'price': offer_price,
                    'datetime': datetime.datetime.now(),
                    'auction_id': slug,
                }
                # Check whether user already made an offer. If he did,
                # replace it with the new one.
                old_offer = yield db.offers.find_one({
                    'username': offer['username'],
                    'auction_id': slug
                })

                if old_offer:
                    result = yield db.offers.update({'_id': old_offer[
                        '_id']}, offer)
                else:
                    result = yield db.offers.insert(offer)

                self.redirect('/auction/' + slug)


class ProfileHandler(BaseHandler):
    @tornado.web.authenticated
    @gen.coroutine
    def get(self, username):
        if username == self.current_user.decode('utf-8'):
            u_auction = yield self.find_auctions(username)
            u_offer = yield self.find_offers(username)
            self.render('profile.html', u_auction=u_auction, u_offer=u_offer)
        else:
            self.write('Sorry, restricted access')


class NewHandler(BaseHandler):
    @tornado.web.authenticated
    def get(self):
        self.render('new.html')

    @tornado.web.authenticated
    @gen.coroutine
    def post(self):
        name = self.get_argument('name')
        description = self.get_argument('description')
        price_min = int(self.get_argument('price'))
        end_date = self.get_argument('end_date')

        new_auction = {
            'username': self.current_user.decode('utf-8'),
            'name': name,
            'description': description,
            'price_min': price_min,
            'start_date': datetime.datetime.now(),
            'end_date': end_date
        }

        result = yield db.auctions.insert(new_auction)
        self.redirect(self.get_argument('next', '/'))


class AuthCreateHandler(BaseHandler):
    def get(self):
        self.render('create_user.html')

    @gen.coroutine
    def post(self):
        username = self.get_argument('username')
        if self.does_user_exist(username):
            raise tornado.web.HTTPError(400, 'user already created')

        hashed_password = yield executor.submit(
            bcrypt.hashpw, tornado.escape.utf8(self.get_argument('password')),
            bcrypt.gensalt())

        user = {'username': username, 'password': hashed_password}
        db.users.insert(user)
        self.set_secure_cookie('auction_user', username)
        self.redirect(self.get_argument('next', '/'))


class AuthLoginHandler(BaseHandler):
    def get(self):
        self.render('login.html')

    @gen.coroutine
    def post(self):
        username = self.get_argument('username')
        if not self.does_user_exist(username):
            self.redirect('/auth/create')

        user = yield db.users.find_one({'username': username})

        hashed_password = yield executor.submit(
            bcrypt.hashpw,
            tornado.escape.utf8(self.get_argument('password')),
            tornado.escape.utf8(user['password'].decode('utf-8')))

        if hashed_password == user['password']:
            self.set_secure_cookie('auction_user', username)
            self.redirect(self.get_argument('next', '/'))
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
