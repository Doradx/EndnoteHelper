# @FileName: 
# @Time    : 2021/10/27
# @Author  : Dorad, cug.xia@gmail.com
# @Blog    : https://blog.cuger.cn
import datetime
import re, os, re, shutil, json
import time

from lxml import html
import requests
import sqlite3
import logging

logPath = 'log'
logFilename = '%s.log' % (datetime.datetime.today().strftime('%Y-%m-%d'))

if (not os.path.exists(logPath)):
    os.makedirs(logPath)

logging.basicConfig(handlers=[logging.FileHandler(filename=os.path.join(logPath, logFilename),
                                                  encoding='utf-8', mode='a+')],
                    format='%(asctime)s  %(filename)s : %(levelname)s  %(message)s',
                    level=logging.ERROR)
logging.getLogger("pdfminer").setLevel(logging.ERROR)
logging.getLogger("urllib3").setLevel(logging.ERROR)


def cleanOldLog():
    try:
        now = datetime.datetime.now()
        for logFile in os.listdir(logPath):
            file = os.path.join(logPath, logFile)
            if (datetime.datetime.strptime(logFile.split('.')[0], '%Y-%m-%d') + datetime.timedelta(days=7) > now):
                continue
            os.remove(file)
    except Exception as e:
        logging.error('Failed to clean the old log file, ' + str(e))
        return False


cleanOldLog()


def loadConfig(path='config.json'):
    config = {
        "endnotePath": "",
        "scan": {
            "scihubHost": "https://sci-hub.ee",
            "scanInterval": 2,
            "numberOfProcess": 3
        }
    }
    if (not os.path.exists(path)):
        saveConfig(config)
    else:
        with open(path, 'r') as f:
            config = json.load(f)
            f.close()
            logging.debug('Success load config.')
    return config


def saveConfig(config, path='config.json'):
    with open(path, 'w') as f:
        json.dump(config, f, indent=2)
        f.close()
    return


configFilePath = 'config.json'
CONFIG = loadConfig(configFilePath)

SCIHUB_HOST = [
    'https://sci-hub.se',
    'https://sci-hub.st',
    'https://sci-hub.ru',
]

SCIHUB_HOST_KEY = 1


# 状态: 队列中/查找中/无PDF/存储失败/

class EndNoteModel(object):
    def __init__(self, libPath, libName):
        self.libPath = libPath
        self.libName = libName
        self.pdfPath = os.path.join(libPath, libName + '.Data', 'PDF')
        self.sdbDB = os.path.join(libPath, libName + '.Data', 'sdb', 'sdb.eni')
        self.pdbDB = os.path.join(libPath, libName + '.Data', 'sdb', 'pdb.eni')
        self.helpDB = os.path.join(libPath, libName + '.Data', 'sdb', 'helper.eni')
        self.__createHelperDbIfNotExist()

    def getUnfinishTasks(self, firstTime=False):
        try:
            if (firstTime):
                self.__cleanHelperRecords()
            refs = self.__searchReferencesWithDoiNoPdf()
            insertRefs = [(r['id'], r['doi'], r['year'], r['title'], r['author'], 'Waiting', '') for r in refs]
            # push refs to helper database
            conn = sqlite3.connect(self.helpDB)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.executemany("INSERT INTO refs_helper(id,doi,year,title,author,status,remark) VALUES(?,?,?,?,?,?,?)", insertRefs)
            conn.commit()
            # if (firstTime):
            #     cursor.execute("SELECT * FROM refs_helper WHERE status IS NULL OR status NOT LIKE '成功'")
            #     refs = cursor.fetchall()
            #     refs = [dict(ref) for ref in refs]
            return refs
        except Exception as e:
            logging.error('Failed to get task from refs, ' + str(e))
            return False

    def getRefSearchRecords(self):
        try:
            conn = sqlite3.connect(self.helpDB)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM refs_helper ORDER BY id DESC")
            refs = cursor.fetchall()
            refs = [dict(ref) for ref in refs]
            return refs
        except Exception as e:
            logging.error('Failed to query records from refs, ' + str(e))
            return False

    def savePdf(self, ref, pdfPath):
        logging.debug("Saving pdf to database, doi: %s, title: %s" % (ref['doi'], ref['title']))
        # ref={id:xxx,title:xxx,year:xxx}
        try:
            # 1. move pdf file to disk
            if (not os.path.isfile(pdfPath) or not ref):
                return False
            text = EndNoteModel.getTextFromPdf(pdfPath).replace('"', '').replace("'", '')
            authorName = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fa5]", "", ref['author'].split(',')[0])
            pdfFilename = authorName + '-' + ref['year'] + '-' + ref['title'][:min(len(ref['title']), 30)] + '.pdf'
            # 生成一个十位数的文件夹
            dstPdfPath = os.path.join(self.__generateNewPdfFolder(), pdfFilename)
            shutil.move(pdfPath, os.path.join(self.pdfPath, dstPdfPath))
            # 2. insert record to pdf_index
            conn = sqlite3.connect(self.pdbDB)
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO pdf_index (refs_id,subkey,contents) VALUES(%d,"%s","%s")' % (
                    ref['id'], dstPdfPath, text))
            conn.commit()
            conn.close()
            # 3. insert record to file_res
            conn = sqlite3.connect(self.sdbDB)
            cursor = conn.cursor()
            cursor.execute('INSERT INTO file_res (refs_id,file_path,file_type,file_pos) VALUES(%d,"%s",1,0)' % (
                ref['id'], dstPdfPath))
            conn.commit()
            conn.close()
            # mark ref status as finished
            return True
        except Exception as e:
            logging.error('Error when save pdf to Endnote,' + str(e))
            return False

    def __generateNewPdfFolder(self):
        import random, string
        dirname = ''.join(random.sample(string.digits, 10))
        while os.path.exists(os.path.join(self.pdfPath, dirname)):
            dirname = ''.join(random.sample(string.digits, 10))
        os.makedirs(os.path.join(self.pdfPath, dirname))
        return dirname

    def __createHelperDbIfNotExist(self):
        try:
            conn = sqlite3.connect(self.helpDB)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('select * from sqlite_master where type = "table" and name = "refs_helper"')
            if (cursor.fetchone()):
                return True
                # 表不存在
            cursor.execute('''
                        CREATE TABLE "refs_helper" (
                          "id" INTEGER NOT NULL,
                          "doi" TEXT NOT NULL,
                          "year" TEXT,
                          "title" TEXT,
                          "author" TEXT,
                          "status" TEXT,
                          "remark" TEXT,
                          "createdAt" TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                          "updatedAt" TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                          PRIMARY KEY ("id")
                        );
                    ''')
            cursor.execute('''
                CREATE TRIGGER "trigger_created_at"
                AFTER INSERT
                ON "refs_helper"
                FOR EACH ROW
                BEGIN
                  UPDATE refs_helper SET updatedAt = datetime('now','localtime'), createdAt=datetime('now','localtime') WHERE id == NEW.id;
                END;
            ''')
            cursor.execute('''
                CREATE TRIGGER "trigger_updated_at"
                AFTER UPDATE
                ON "refs_helper"
                FOR EACH ROW
                BEGIN
                  UPDATE refs_helper SET updatedAt = datetime('now','localtime') WHERE id == NEW.id;
                END;
            ''')
            conn.commit()
            return True
        except Exception as e:
            logging.error('Failed to create the refs_helper table, ' + str(e))
            return False

    def __cleanHelperRecords(self):
        try:
            conn = sqlite3.connect(self.helpDB)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("DELETE FROM 'refs_helper'")
            conn.commit()
            return True
        except Exception as e:
            logging.error('Error when clean the help records' + str(e))
            return False

    def updateRefStatusInHelperDb(self, ref, status, remark=''):
        logging.info('Reference %s %s, %s' % (ref['title'], status, remark))
        try:
            conn = sqlite3.connect(self.helpDB)
            cursor = conn.cursor()
            cursor.execute(
                """UPDATE refs_helper SET status="%s",remark="%s" WHERE id = %d""" % (status, remark, ref['id']))
            conn.commit()
            return True
        except Exception as e:
            logging.info('Failed to update the reference status in helper database, ' + str(e))
            return False

    def __searchReferencesWithDoiNoPdf(self):
        try:
            conn = sqlite3.connect(self.sdbDB)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("ATTACH DATABASE '%s' as helper" % (self.helpDB))
            cursor.execute(
                'SELECT id,year,title,author,electronic_resource_number as doi FROM refs WHERE trash_state=0 AND LENGTH(electronic_resource_number) AND id NOT IN (SELECT refs_id FROM file_res) AND id NOT IN (SELECT id FROM helper.refs_helper)')
            data = cursor.fetchall()
            cursor.execute("DETACH DATABASE helper")
            return [dict(r) for r in data]
        except Exception as e:
            logging.error('Error when search reference with no pdf' + str(e))
            return False

    @staticmethod
    def getTextFromPdf(pdfPath):
        from io import StringIO
        from pdfminer.converter import TextConverter
        from pdfminer.layout import LAParams
        from pdfminer.pdfdocument import PDFDocument
        from pdfminer.pdfinterp import PDFResourceManager, PDFPageInterpreter
        from pdfminer.pdfpage import PDFPage
        from pdfminer.pdfparser import PDFParser
        output_string = StringIO()
        with open(pdfPath, 'rb') as in_file:
            parser = PDFParser(in_file)
            doc = PDFDocument(parser)
            rsrcmgr = PDFResourceManager()
            device = TextConverter(rsrcmgr, output_string, laparams=LAParams())
            interpreter = PDFPageInterpreter(rsrcmgr, device)
            for page in PDFPage.create_pages(doc):
                interpreter.process_page(page)
            in_file.close()
        return output_string.getvalue()

    @staticmethod
    def searchPdfBasedOnDoi(doi):
        try:
            host = re.findall(r"(https?\:\/\/[\w.\-]+)", CONFIG['scan']['scihubHost'])
            if (not len(host)):
                logging.error('SCI-HUB host is error, host: %s' % (CONFIG['scan']['scihubHost']))
                host = 'https://sci-hub.se'
            else:
                host = host[0]
            r = requests.get(host + '/' + doi, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/63.0.3239.132 Safari/537.36 QIHU 360SE'
            }, timeout=10)
            if (r.status_code != 200):
                return False
            srcList = html.fromstring(r.text).xpath('//*[@id="pdf"]/@src')
            if (not len(srcList)):
                return False
            url = srcList[0]
            if (not re.match('(http|https):\/\/([\w.]+\/?)\S*', url)):
                if url.startswith('//'):
                    url = 'https:' + url
                if '#' in url:
                    url = url[:url.find('#')]
            return url
        except Exception as e:
            logging.error('Error when search reference with no pdf, doi: ' + doi + str(e))
            return False

    @staticmethod
    def downloadPdf(url, savePath):
        try:
            r = requests.get(url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/63.0.3239.132 Safari/537.36 QIHU 360SE'
            })
            if (r.status_code != 200):
                return False
            import hashlib
            filename = hashlib.md5((url + str(time.time())).encode('utf-8')).hexdigest() + ".pdf"
            if (re.findall("\/([\w\-_]+.pdf)", url)):
                filename = re.findall("\/([\w\-_]+.pdf)", url)[0]
            if ("Content-Disposition" in r.headers.keys() and r.headers["Content-Disposition"]):
                filename = re.findall("filename=(.+)", r.headers["Content-Disposition"])[0]
            if not os.path.exists(savePath):
                os.makedirs(savePath)
            fullFilenameWithPath = os.path.join(savePath, filename)
            if (not os.path.exists(savePath)):
                os.makedirs(savePath)
            with open(fullFilenameWithPath, "wb") as file:
                file.write(r.content)
                file.close()
            return fullFilenameWithPath
        except Exception as e:
            logging.error('Error when download pdf, url: ' + url + str(e))
            return False


import multiprocessing as mp


class RefHandler(mp.Process):
    def __init__(self, endModel: EndNoteModel, taskQ: mp.SimpleQueue, runnning: mp.Value):
        super(RefHandler, self).__init__()
        self.endModel = endModel  # endnote model
        self.taskQ = taskQ  # get task from queue
        self.running = runnning

    def run(self) -> None:
        while self.running.value:
            if self.taskQ.empty():
                time.sleep(5)
                continue
            time.sleep(0.5)
            ref = self.taskQ.get()
            logging.debug('Got task %d, doi: %s, title: %s' % (ref['id'], ref['doi'], ref['title']))
            self.endModel.updateRefStatusInHelperDb(ref, 'Searching', '')
            pdfUrl = self.endModel.searchPdfBasedOnDoi(ref['doi'])
            if (not pdfUrl):
                logging.debug("Can't find the PDF in sci-hub.")
                self.endModel.updateRefStatusInHelperDb(ref, 'Failed', "Can't find the PDF in sci-hub.")
                continue
            if (not self.running.value):
                continue
            self.endModel.updateRefStatusInHelperDb(ref, 'Downloading', pdfUrl)
            pdfPath = self.endModel.downloadPdf(pdfUrl, 'download')
            if (not pdfPath):
                self.endModel.updateRefStatusInHelperDb(ref, 'Failed', 'Failed to download the PDF file.')
                continue
            savePdfStatus = self.endModel.savePdf(ref, pdfPath)
            if (not savePdfStatus):
                self.endModel.updateRefStatusInHelperDb(ref, 'Failed', 'Failed to save the PDF file.')
                continue
            self.endModel.updateRefStatusInHelperDb(ref, 'Succeed', 'Succeed to link the PDF.')
        logging.info('Process RefHandler stopped.')


class RefMonitor(mp.Process):
    def __init__(self, dbPath, scanInterval=5, refHandlerNumber=5):
        super(RefMonitor, self).__init__()
        self.endnoteModel = EndNoteModel(os.path.dirname(dbPath), os.path.basename(dbPath).replace('.enl', ''))
        self.taskQ = mp.SimpleQueue()
        self.refHandlerNumber = refHandlerNumber
        self.running = mp.Value('i', 1)
        self.scanInterval = scanInterval
        self.refHandlerProcesses = []

    def setScanInterval(self, scanInterval):
        self.scanInterval = scanInterval

    def run(self) -> None:
        logging.debug('Monitor start.')
        firstTimeRun = True
        for i in range(0, self.refHandlerNumber):
            self.refHandlerProcesses.append(RefHandler(self.endnoteModel, self.taskQ, self.running))
            self.refHandlerProcesses[i].start()
            logging.debug('Handler %d start.' % (i))
        while self.running.value:
            # scan the endnote
            refs = self.endnoteModel.getUnfinishTasks(firstTimeRun)
            firstTimeRun = False
            logging.debug('New task number: %d' % (len(refs)))
            # save to ref helper
            for ref in refs:
                self.taskQ.put(ref)
                self.endnoteModel.updateRefStatusInHelperDb(ref, 'Queueing', 'Queueing for search.')
            time.sleep(self.scanInterval)
        for i in range(0, self.refHandlerNumber):
            self.refHandlerProcesses[i].terminate()
            # self.refHandlerProcesses[i].join()
            logging.debug('Handler %d stop.' % (i))
        logging.info('Process RefMonitor stopped.')

    def stop(self):
        self.running.value = 0

    def isRunning(self):
        return self.running.value


if __name__ == '__main__':
    # print(searchAndDownloadPdfBasedDOI('10.3390/sym12061047', './download'))
    # searchPapersWithDoiNoPdf(".\PaperDatabase\PAPER-DATABASE-20210317.Data\sdb\sdb.eni",".\PaperDatabase\PAPER-DATABASE-20210317.Data\sdb\pdb.eni")
    # print(getTextFromPdf('./download/sym12061047.pdf'))
    # edDB = EndNoteModel('PaperDatabase', 'PAPER-DATABASE-20210317')
    # refs = edDB.getTasks(True)
    monitor = RefMonitor('PaperDatabase/PAPER-DATABASE-20210317.enl', 2, 5)
    monitor.start()
    # time.sleep(30)
    # monitor.stop()
    monitor.join()

    # edDB.createHelperDbIfNotExist()
    # refs = edDB.searchReferencesWithDoiNoPdf()
    # logging.info('Total reference need deal with: %d' % (len(refs)))
    # for i in range(0, len(refs)):
    #     ref = refs[i]
    #     logging.debug('%d/%d - handling %s' % (i, len(refs), str(ref)))
    #     pdfUrl = edDB.searchPdfBasedOnDoi(ref['doi'])
    #     if (pdfUrl):
    #         pdfPath = edDB.downloadPdf(pdfUrl, 'download')
    #         edDB.savePdf(ref, pdfPath)
    #         logging.info('success import' + str(ref))
    # logging.info('All finished.')
