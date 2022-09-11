import shutil
import os
import os.path as path
import sys

from distutils.dir_util import copy_tree
from subprocess import call
import platform
from datetime import datetime


def get_python():
    if platform.system() == "Windows":
        return "python"
    else:
        return "python3"


def copytree(src, dst, symlinks=False, ignore=None):
    from distutils.dir_util import copy_tree

    if not os.path.exists(dst):
        os.mkdir(dst)

    copy_tree(src, dst)


def download_and_extract_toolchain(directory):
    import urllib.request
    import zipfile
    archive = path.join(directory, 'update.zip')

    if not path.exists(archive):
        url = "https://codeload.github.com/80LK/innercore-mod-toolchain/zip/master"
        print("downloading toolchain archive from " + url)
        urllib.request.urlretrieve(url, archive)
    else: 
        print("toolchain archive already exists in " + directory)

    print("extracting toolchain to " + directory)

    with zipfile.ZipFile(archive, 'r') as zip_ref:
        zip_ref.extractall(directory)

    try:
        copytree(path.join(directory, "innercore-mod-toolchain-master/toolchain-mod"), directory)
        shutil.rmtree(path.join(directory, "innercore-mod-toolchain-master"))
    except Exception as ex: 
        print(ex)
    finally:
        os.remove(archive)
        if not path.exists(path.join(directory, "toolchain")):
            print("an error occured while extracting toolchain archive, please, retry the operation")
            exit()


if(len(sys.argv) > 1):
    directory = sys.argv[1]
    os.makedirs(directory)
else: 
    directory = '.'

if not path.exists(path.join(directory, "toolchain")):
    print("Toolchain not found.")
    exit()
    

download_and_extract_toolchain(directory)

last_update_path = path.join(directory, "toolchain", "bin", ".last_update")
with open(last_update_path, "w", encoding="utf-8") as last_update_file:
    last_update_file.write(datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"))

os.remove(path.join(directory, "toolchain-update.py"))
print("Toolchain update successful")