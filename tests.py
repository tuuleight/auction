import unittest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait


class AuctionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.driver = webdriver.Firefox()
        cls.driver.maximize_window()

        cls.driver.get('http://localhost:8888/')

    def test_new_acc(self):
        new_account = self.driver.find_element_by_link_text('New account')
        new_account.click()

        self.name = self.driver.find_element_by_name('username')
        self.name.clear()
        self.name.send_keys('and')
        self.password = self.driver.find_element_by_name('password')
        self.password.clear()
        self.password.send_keys('and')
        self.submit_button = self.driver.find_element_by_name('submit')
        self.submit_button.click()

        self.assertEqual('400: Bad Request', self.driver.title)

    @classmethod
    def tearDownClass(cls):
        cls.driver.quit()

if __name__ == '__main__':
    unittest.main()
