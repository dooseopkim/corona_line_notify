import os
import sys
import requests
import json
import re
import io
import logging, logging.handlers

from datetime import datetime
from bs4 import BeautifulSoup
from configparser import ConfigParser


class App:

    def __init__(self, WD):
        self.WD = WD

        self._logger = None
        self._data = None
        self._next = None
        self._diff = None

    # - at
    @staticmethod
    def _at():
        return datetime.now().strftime('%Y/%m/%d %H:%M:%S')

    # - extract number
    @staticmethod
    def _asInt(str_):
        try:
            return int(re.findall(r"[0-9,]{1,}", str_)[0].replace(',',''))
        except Exception as e:
            return 0

    # - comma
    @staticmethod
    def _comma(int_):
        return "{:,}".format(int_)

    # - Parser
    @staticmethod
    def _parse(soup):
        result = {}
        div_ = soup.find('div', class_='bvc_txt')

        # title
        result['title'] = div_.find('p', class_='s_descript').text

        # image
        result['image'] = div_.find('div', class_='box_image').find('img')['src']

        # data
        result['data'] = []
        for li in div_.find('ul', class_='s_listin_dot').find_all('li'):
            result['data'].append(App._asInt(li.text))

        return result

    @staticmethod
    def _msg(_next, _diff):
        messages = []
        messages.append('\n======================\n')
        messages.append('{title}\n'.format(title=_next['title'].replace('19 ', '19\n')))
        messages.append('======================\n')
        messages.append('※ 환자 수 변동\n')
        messages.append('▶ 확진환자 수 증가 : {}\n'.format(App._comma(_diff['confirm'])))
        messages.append('▶ 격리해제 환자 수 증가 : {}\n'.format(App._comma(_diff['discharge'])))
        messages.append('▶ 사망자 수 증가 : {}\n\n'.format(App._comma(_diff['death'])))
        messages.append('※ 현재 환자 수 현황\n')
        messages.append('▶ 확진환자 수 : {}\n'.format(App._comma(_next['data'][0])))
        messages.append('▶ 확진환자 격리해제 수 : {}\n'.format(App._comma(_next['data'][1])))
        messages.append('▶ 사망자 수 : {}\n'.format(App._comma(_next['data'][2])))
        messages.append('▶ 검사진행 수 : {}\n\n'.format(App._comma(_next['data'][3])))
        messages.append('Check at: {}\n'.format(App._at()))
        messages.append('======================\n')
        messages.append('▷ 더 보기 : {}\n'.format(_next['bbs']))
        messages.append('▷ 확진자 동선 : {}'.format(_next['move']))
        return ''.join(messages)

    # - 로거 초기화
    def _initLogger(self):
        log_dir = os.path.join(self.WD, 'logs')
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)

        logger = logging.getLogger('MaskBot')
        logger.setLevel(logging.INFO)
        fmt = logging.Formatter('%(asctime)s - [%(levelname)s|%(filename)s:%(lineno)s] - %(message)s')

        st_handler = logging.StreamHandler()
        f_handler = logging.handlers.RotatingFileHandler(os.path.join(log_dir, 'maskchk.log'), 'a', 10 * 1024 * 1024, 5)

        st_handler.setFormatter(fmt)
        f_handler.setFormatter(fmt)

        logger.addHandler(st_handler)
        logger.addHandler(f_handler)

        self._logger = logger

    # - 환경설정 파일 초기화
    def _initConf(self, file_name='app.conf'):
        file = os.path.join(self.WD, file_name)
        parser = ConfigParser()
        parser.read(file, encoding='utf-8-sig')
        self._conf = parser

    # - 데이터 로딩
    def _load(self, file_name='data.json'):
        file = os.path.join(self.WD, file_name)

        self._logger.info('Loading data.. {file}'.format(file=file))

        # 1st Loading
        if not os.path.isfile(file):
            self._logger.info('First loading.. write file & exit')

            self._data = {'data':[]}
            self._save()

            sys.exit()

        with open(file, 'r', encoding='utf-8') as f:
            tmp = json.load(f)
            tmp['data'] = tmp['data'][:10]
            self._data = tmp

    # - 데이터 저장
    def _save(self, file_name='data.json'):
        file = os.path.join(self.WD, file_name)

        self._logger.info('Saving data.. {file}'.format(file=file))

        if self._next:
            self._data['data'].insert(0, self._next['data'])

        with open(file, 'w', encoding='utf-8') as f:
            json.dump(self._data, f, ensure_ascii=False)

    #   - Check the change
    def _isChange(self):
        try:
            self._logger.info('Check changes number of patients ')

            prev = self._data['data'][0]
            next = self._next['data']

            self._diff = dict()
            self._diff['confirm'] = next[0] - prev[0]
            self._diff['discharge'] = next[1] - prev[1]
            self._diff['death'] = next[2] - prev[2]

            return self._diff['confirm'] != 0 or self._diff['discharge'] != 0 or self._diff['death'] != 0
        except Exception as e:
            self._logger.warning(e)
            return False

    # - Short url with Naver API
    def _shortURL(self, url):
        try:
            self._logger.info('Call API Naver shortURL')

            NAVER = self._conf['naverAPI']
            response = requests.post(
                NAVER['URL'],
                headers={
                    'X-Naver-Client-Id': NAVER['clientID'],
                    'X-Naver-Client-Secret': NAVER['clientSecret']
                },
                data={
                    'url': url.encode('utf-8')
                }
            )

            if response.json()['code'] != '200':
                raise Exception(response.json()['message'])

            return response.json()['result']['url']

        except Exception as e:
            self._logger.warning(e)
            return url

    # - Send LINE notification
    def _sendNotification(self):
        try:
            self._logger.info('Send LINE notification..')

            TARGET_URL = self._conf['notify']['URL']
            TOKEN = self._conf['notify']['TOKEN']

            # get image
            image_url = self._conf['default']['HOST'] + self._next['image']
            response = requests.get(image_url)
            imageFile = io.BytesIO(response.content)

            # urls
            self._next['bbs'] = self._shortURL(self._conf['default']['MAIN'])
            self._next['move'] = self._shortURL(self._conf['default']['MOVE'])

            message = App._msg(self._next, self._diff)

            headers = {'Authorization': 'Bearer {TOKEN}'.format(TOKEN=TOKEN)}
            data = {'message': message}
            files = {'imageFile': imageFile}

            response = requests.post(TARGET_URL, headers=headers, data=data, files=files)

            if response.status_code != 200:
                raise Exception("Sending message is fail..")
        except Exception as e:
            self._logger.error(e)

    # - 크롤링
    def _crawl(self):
        try:
            TARGET_URL = self._conf['default']['BBS']
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.106 Safari/537.36"
            }

            response = requests.get(TARGET_URL, headers=headers)
            if response.status_code != 200:
                raise Exception("Wrong page.. Check your URL")

            self._logger.info('Crawling... {}'.format(response.url))

            html = response.text
            soup = BeautifulSoup(html, 'lxml')

            self._next = self._parse(soup)

        except Exception as e:
            self._logger.error(e)

    def run(self):
        try:

            # Initialize
            self._initLogger()
            self._initConf()

            self._logger.info('Start process')

            # load data
            self._load()

            # Crawling
            self._crawl()

            # Check the change
            if self._isChange():
               self._sendNotification()

            # Save data
            self._save()

        except Exception as e:
            _, _, tb = sys.exc_info()
            self._logger.error('line : {} - {}'.format(tb.tb_lineno, e))
        finally:
            self._logger.info('End Process')


def main():
    WD = os.path.dirname(os.path.realpath(__file__))

    app = App(WD)
    app.run()


if __name__ == "__main__":
    main()

