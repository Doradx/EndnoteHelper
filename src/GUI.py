# @FileName: 
# @Time    : 2021/10/28
# @Author  : Dorad, cug.xia@gmail.com
# @Blog    : https://blog.cuger.cn

import logging
import os, webbrowser
import tkinter as tk
from tkinter import ttk, font, filedialog, simpledialog
from pystray import Icon, Menu, MenuItem
from PIL import Image
from src.CORE import RefMonitor, EndNoteModel, loadConfig, saveConfig, configFilePath
import logging

logger = logging.getLogger("GUI")
logger.setLevel(logging.DEBUG)


class SystemTray():
    def __init__(self):
        self.startService()
        self.initUi()

    def initUi(self):
        quitItem = MenuItem('Exit', self.quit)
        aboutItem = MenuItem('About Author', self.about)
        changeEndnoteDbItem = MenuItem('Database Setting', self.openSetting)
        openConfigFileItem = MenuItem('Advance Setting', self.advancedSetting)
        statusItem = MenuItem('Task View', self.openTaskList)
        RunningItem = MenuItem('Start', self.startService, checked=self.isRunning)
        StopItem = MenuItem('Stop', self.stopService, checked=self.isStop)
        self.icon = Icon("EndnoteHelper", Image.open('./res/icon.png'), "EndNoteHelper - v0.1.4", Menu(
            statusItem, MenuItem('Service State', Menu(
                RunningItem, StopItem
            )), changeEndnoteDbItem, openConfigFileItem, aboutItem, quitItem
        ))

        self.icon.run()

    def startService(self):
        self.config = loadConfig(configFilePath)
        if (not len(self.config['endnotePath']) or not os.path.exists(self.config['endnotePath'])):
            logger.debug('There is no endnote path.')
            self.openSetting()
            return False
        if (hasattr(self, 'refMonitor') and self.refMonitor):
            self.stopService()
        self.refMonitor = RefMonitor(self.config['endnotePath'], self.config['scan']['scanInterval'],
                                     self.config['scan']['numberOfProcess'])
        self.refMonitor.start()
        return True

    def isRunning(self, *args):
        if (hasattr(self, 'refMonitor') and self.refMonitor):
            return True if self.refMonitor.running.value else False
        else:
            return False

    def isStop(self, *args):
        return not self.isRunning()

    def restartService(self):
        logger.debug('Restarting...')
        self.stopService()
        self.startService()

    def stopService(self):
        if (hasattr(self, 'refMonitor') and self.refMonitor):
            self.refMonitor.stop()

    def openTaskList(self):
        # if (hasattr(self, 'settingWindow') and self.settingWindow):
        #     self.settingWindow.destory()
        logger.debug('Stopping')
        endnoteModel = EndNoteModel(os.path.dirname(self.config['endnotePath']),
                                    os.path.basename(self.config['endnotePath']).replace('.enl', ''))
        taskWindow = TaskListWindow(endnoteModel)
        self.taskWindow = taskWindow
        self.taskWindow.mainloop()

    def openSetting(self):
        changeDbWindow = EndnoteDbPathSettingWindow(self.config)
        changeDbWindow.mainloop()
        # setting closed
        self.config = loadConfig(configFilePath)
        if (len(self.config['endnotePath']) and os.path.exists(self.config['endnotePath'])):
            self.restartService()
        else:
            self.stopService()

    def advancedSetting(self):
        os.startfile(configFilePath)

    def about(self):
        webbrowser.open('https://blog.cuger.cn')
        pass

    def quit(self):
        self.stopService()
        if (hasattr(self, 'icon') and self.icon):
            self.icon.stop()


class EndnoteDbPathSettingWindow(tk.Tk):
    def __init__(self, config):
        super(EndnoteDbPathSettingWindow, self).__init__()
        self.config = config
        self.endnotePath = self.config['endnotePath']
        self.initUI()

    def initUI(self):
        self.title('Setting')
        w, h = 400, 200
        ws = self.winfo_screenwidth()
        hs = self.winfo_screenheight()
        x = (ws / 2) - (w / 2)
        y = (hs / 2) - (h / 2)
        self.geometry('%dx%d+%d+%d' % (w, h, x, y))
        # self.resizable(False, False)
        fontStyle = font.Font(family="Microsoft YaHei", size=14)
        tk.Label(self, text="EndNote Helper Setting", font=("Microsoft YaHei", 20)).pack(side=tk.TOP, expand=tk.TRUE)
        tk.Label(self, text="Dorad, cug.xia@gmail.com", font=("Microsoft YaHei", 12)).pack(side=tk.TOP, expand=tk.TRUE)
        p = tk.Frame(self)
        p.pack(side=tk.TOP, expand=tk.TRUE)
        tk.Label(p, text="Database:", font=fontStyle).grid(row=0, column=0, padx=(10, 10), pady=(10, 0))
        endnotePathEntry = tk.Entry(p, width=30)
        endnotePathEntry.insert(0, self.endnotePath)
        endnotePathEntry.grid(row=0, column=1, columnspan=1, padx=(10, 10), pady=(10, 0))
        endnotePathEntry.configure(state='disabled')
        endnotePathSelectBtn = tk.Button(p, text='SELECT', command=self.selectEndnotePath)
        endnotePathSelectBtn.grid(row=0, column=4, pady=(10, 0))

    def selectEndnotePath(self):
        filename = filedialog.askopenfilename(filetypes=[('EndNote Library', '*.enl')])
        if (not filename):
            logger.warning('No path selected for Endnote Database!')
            return
        self.endnotePath = os.path.abspath(filename)
        self.save()

    def save(self):
        try:
            self.config['endnotePath'] = self.endnotePath
            saveConfig(self.config, configFilePath)
            self.destroy()
        except Exception as e:
            return False


class TaskListWindow(tk.Tk):
    def __init__(self, enModel: EndNoteModel):
        super(TaskListWindow, self).__init__()
        self.running = True
        self.enModel = enModel
        self.initUI()
        self.refresh()

    def initUI(self):
        self.title('Reference List - Dorad, https://blog.cuger.cn')
        self.geometry('900x600')
        columns = ("ID", "TITLE", "DOI", "STATE", "REMARK", "UPDATED AT")
        tv = ttk.Treeview(self, show='headings', columns=columns, height=20)
        tv.column("ID", width=50, anchor='center', stretch=tk.NO)
        tv.column("TITLE", minwidth=200, anchor='w')
        tv.column("DOI", minwidth=80, anchor='w')
        tv.column("STATE", minwidth=50, width=80, anchor='center', stretch=tk.NO)
        tv.column("REMARK", minwidth=60, anchor='center')
        tv.column("UPDATED AT", minwidth=80, anchor='w', stretch=tk.NO)
        for col in list(columns):
            tv.heading(col, text=col)
        tv.tag_configure('Succeed', background='#99CC99')
        tv.tag_configure('Searching', background='#FFCC99')
        tv.tag_configure('Downloading', background='#CCFF99')
        tv.tag_configure('Failed', background='#CCCCCC')
        scrollbar = ttk.Scrollbar(self, orient="vertical")
        tv.configure(yscroll=scrollbar.set, selectmode="browse")
        scrollbar.config(command=tv.yview)
        tv.pack(side=tk.LEFT, fill=tk.BOTH, expand=tk.TRUE)
        self.table = tv

    def clearAndPushRefList(self, refs):
        for item in self.table.get_children():
            self.table.delete(item)
        if (not refs):
            return False
        for i in range(len(refs)):
            r = refs[i]
            self.table.insert('', tk.END,
                              values=(r['id'], r['title'], r['doi'], r['status'], r['remark'], r['updatedAt']),
                              tags=(r['status'],))

    def refresh(self):
        if self.running:
            refs = self.enModel.getRefSearchRecords()
            if (not refs):
                return False
            self.clearAndPushRefList(refs)
            self.after(1000, self.refresh)

    def destroy(self):
        self.running = False
        super().destroy()


if __name__ == "__main__":
    # edDB = EndNoteModel('PaperDatabase', 'PAPER-DATABASE-20210317')
    # app = TaskListWindow(edDB)
    # app.mainloop()
    icon = SystemTray()
    # setting = EndnoteDbPathSettingWindow(loadConfig())
    # setting.mainloop()
