# @FileName: 
# @Time    : 2021/10/28
# @Author  : Dorad, cug.xia@gmail.com
# @Blog    : https://blog.cuger.cn
from src.GUI import SystemTray
import multiprocessing

def run():
    SystemTray()


if __name__ == '__main__':
    multiprocessing.freeze_support()
    run()
