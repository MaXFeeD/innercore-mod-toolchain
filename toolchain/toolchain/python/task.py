import sys
import os
from os.path import join, exists, basename, isfile, isdir, splitext
import platform
import time

from utils import ensure_directory, ensure_file_dir, clear_directory, copy_file, copy_directory

make_config = None
registered_tasks = {}
locked_tasks = {}
devnull = open(os.devnull, "w")

def get_make_config():
	global make_config
	if make_config is None:
		from make_config import make_config as config
		make_config = config
	return make_config

def lock_task(name, silent = True):
	path = get_make_config().get_path(f"toolchain/build/lock/{name}.lock")
	ensure_file_dir(path)
	await_message = False

	if exists(path):
		while True:
			try:
				if exists(path):
					os.remove(path)
				break
			except IOError:
				if not await_message:
					await_message = True
					if not silent:
						sys.stdout.write(f"Task {name} is locked by another process, waiting for it to unlock.")
					if name in locked_tasks:
						error("ERROR: Dead lock detected", code=-2)
				if not silent:
					sys.stdout.write(".")
					sys.stdout.flush()
				time.sleep(0.25)
	if await_message:
		if not silent:
			print("")
	open(path, "tw").close()
	locked_tasks[name] = open(path, "a")

def unlock_task(name):
	if name in locked_tasks:
		locked_tasks[name].close()
		del locked_tasks[name]
	path = get_make_config().get_path(f"toolchain/build/lock/{name}.lock")
	if isfile(path):
		os.remove(path)

def unlock_all_tasks():
	for name in list(locked_tasks.keys()):
		unlock_task(name)

def task(name, lock = None):
	if lock is None:
		lock = []

	def decorator(func):
		def caller(*args, **kwargs):
			lock_task(name, silent=False)
			for lock_name in lock:
				lock_task(lock_name, silent=False)
			if platform.system() == "Windows":
				os.system("color")
			print(f"\x1b[92m> Executing task: {name}\x1b[0m")
			task_result = func(*args, **kwargs)
			unlock_task(name)
			for lock_name in lock:
				unlock_task(lock_name)
			return task_result

		registered_tasks[name] = caller
		return caller

	return decorator

@task("compileNativeDebug", lock=["native", "cleanup", "push"])
def task_compile_native_debug():
	abi = get_make_config().get_value("debugAbi", None)
	if abi is None:
		abi = "armeabi-v7a"
		print(f"WARNING: No debugAbi value in config, using {abi} as default")
	from native.native_build import compile_all_using_make_config
	return compile_all_using_make_config([abi])

@task("compileNativeRelease", lock=["native", "cleanup", "push"])
def task_compile_native_release():
	abis = get_make_config().get_value("abis", [])
	if abis is None or not isinstance(abis, list) or len(abis) == 0:
		error(f"ERROR: No abis value in config")
	from native.native_build import compile_all_using_make_config
	return compile_all_using_make_config(abis)

@task("compileJavaDebug", lock=["java", "cleanup", "push"])
def task_compile_java_debug():
	from java.java_build import compile_all_using_make_config
	return compile_all_using_make_config()

@task("compileJavaRelease", lock=["java", "cleanup", "push"])
def task_compile_java_release():
	from java.java_build import compile_all_using_make_config
	return compile_all_using_make_config()

@task("buildScripts", lock=["script", "cleanup", "push"])
def task_build_scripts():
	from script_build import build_all_scripts
	return build_all_scripts()

@task("buildResources", lock=["resource", "cleanup", "push"])
def task_resources():
	from script_build import build_all_resources
	return build_all_resources()

@task("buildInfo", lock=["cleanup", "push"])
def task_build_info():
	import json
	from utils import shortcodes
	config = get_make_config()
	with open(config.get_project_path("output/mod.info"), "w") as info_file:
		info = dict(config.get_project_value("info", fallback={"name": "Unnamed"}))
		if "icon" in info:
			del info["icon"]
		if "api" in info:
			del info["api"]

		info["version"] = shortcodes(info["version"])
		info["description"] = shortcodes(info["description"])

		info_file.write(json.dumps(info, indent=" " * 4))
	icon_path = config.get_project_value("info.icon")
	if icon_path is not None and exists(icon_path):
		copy_file(config.get_project_path(icon_path),
				  config.get_project_path("output/mod_icon.png"))
	return 0

@task("buildAdditional", lock=["cleanup", "push"])
def task_build_additional():
	overall_result = 0
	for additional_dir in get_make_config().get_project_value("additional", fallback=[]):
		if "source" in additional_dir and "targetDir" in additional_dir:
			for additional_path in get_make_config().get_project_paths(additional_dir["source"]):
				if not exists(additional_path):
					print("Non existing additional path: " + additional_path)
					overall_result = 1
					break
				target = get_make_config().get_project_path(join(
					"output",
					additional_dir["targetDir"],
					basename(additional_path)
				))
				if isdir(additional_path):
					copy_directory(additional_path, target)
				else:
					ensure_file_dir(target)
					copy_file(additional_path, target)
	return overall_result

@task("pushEverything", lock=["push"])
def task_push_everything():
	from push import push
	return push(get_make_config().get_project_path("output"), False, get_make_config().get_value("pushUnchangedFiles", False))

@task("clearOutput", lock=["assemble", "push", "native", "java"])
def task_clear_output():
	clear_directory(get_make_config().get_project_path("output"))
	return 0

@task("excludeDirectories", lock=["push", "assemble", "native", "java"])
def task_exclude_directories():
	config = get_make_config()
	for path in config.get_project_value("excludeFromRelease", []):
		for exclude in config.get_project_paths(join("output", path)):
			if isdir(exclude):
				clear_directory(exclude)
			elif isfile(exclude):
				os.remove(exclude)
	return 0

@task("buildPackage", lock=["push", "assemble", "native", "java"])
def task_build_package():
	import shutil
	config = get_make_config()
	output_dir = config.get_project_path("output")
	output_file = config.get_project_path(basename(config.get_value("currentProject", "mod")) + ".icmod")
	output_file_tmp = config.get_path("toolchain/build/mod.zip")
	ensure_directory(output_dir)
	ensure_file_dir(output_file_tmp)
	if isfile(output_file):
		os.remove(output_file)
	if isfile(output_file_tmp):
		os.remove(output_file_tmp)
	shutil.make_archive(output_file_tmp[:-4], "zip", output_dir)
	os.rename(output_file_tmp, output_file)
	return 0

@task("launchHorizon")
def task_launch_horizon():
	from subprocess import call
	call([
		make_config.get_adb(),
		"shell", "touch",
		"/storage/emulated/0/games/horizon/.flag_auto_launch"
	], stdout=devnull, stderr=devnull)
	result = call([
		make_config.get_adb(),
		"shell", "monkey",
		"-p", "com.zheka.horizon",
		"-c", "android.intent.category.LAUNCHER", "1"
	], stdout=devnull, stderr=devnull)
	if result != 0:
		print("\x1b[91mNo devices/emulators found, try to use task \"Connect to ADB\"\x1b[0m")
	return 0

@task("stopHorizon")
def stop_horizon():
	from subprocess import call
	result = call([
		make_config.get_adb(),
		"shell",
		"am",
		"force-stop",
		"com.zheka.horizon"
	], stdout=devnull, stderr=devnull)
	if result != 0:
		print("\x1b[91mNo devices/emulators found, try to use task \"Connect to ADB\"\x1b[0m")
	return result

@task("loadDocs")
def task_load_docs():
	from urllib.request import urlopen
	print("Downloading core-engine.d.ts")
	response = urlopen("https://docs.mineprogramming.org/headers/core-engine.d.ts")
	content = response.read().decode("utf-8")

	with open(make_config.get_path("toolchain/declarations/core-engine.d.ts"), "w") as docs:
		docs.write(content)

	print("Complete!")
	return 0

@task("cleanupOutput")
def task_cleanup_output():
	def clean(p):
		_walk = lambda: [f for f in list(os.walk(p))[1:] if exists(f[0])]
		for folder in _walk():
			if len(folder[2]) > 0:
				continue
			if len(folder[1]) > 0:
				for subfolder in folder[1]:
					clean(join(folder[0], subfolder))
				for folder2 in _walk():
					if len(folder2[1]) == 0 and len(folder2[2]) == 0:
						os.rmdir(folder2[0])
	path = make_config.get_project_path("output")
	if exists(path):
		clean(path)
	return 0

@task("updateIncludes")
def task_update_includes():
	from functools import cmp_to_key
	from mod_structure import mod_structure
	from includes import Includes, temp_directory

	def libraries_first(a, b):
		la = a["type"] == "library"
		lb = b["type"] == "library"
		if la == lb:
			return 0
		elif la:
			return -1
		else:
			return 1

	sources = sorted(make_config.get_value("sources", fallback=[]), key=cmp_to_key(libraries_first))
	for item in sources:
		_source = item["source"]
		_target = item["target"] if "target" in item else None
		_type = item["type"]
		_includes = item["includes"] if "includes" in item else ".includes"
		if _type not in ("main", "library", "preloader"):
			print(f"Skipped invalid source with type {_type}")
			continue
		for source_path in make_config.get_paths(_source):
			if not exists(source_path):
				print(f"Skipped non existing source path {_source}")
				continue
			target_path = _target if _target is not None else f"{splitext(basename(source_path))[0]}.js"
			declare = {
				"sourceType": {
					"main": "mod",
					"launcher": "launcher",
					"preloader": "preloader",
					"library": "library"
				}[_type]
			}
			if "api" in item:
				declare["api"] = item["api"]
			try:
				dot_index = target_path.rindex(".")
				target_path = target_path[:dot_index] + "{}" + target_path[dot_index:]
			except ValueError:
				target_path += "{}"
			mod_structure.update_build_config_list("compile")
			incl = Includes.invalidate(source_path, _includes)
			incl.create_tsconfig(join(temp_directory, basename(target_path)))
	return 0

@task("connectToADB")
def task_connect_to_adb():
	import re

	ip = None
	port = None
	pattern = re.compile(r"(\d{1,3}.\d{1,3}.\d{1,3}.\d{1,3}):(\d{4})")
	for arg in sys.argv:
		match = pattern.search(arg)
		if match:
			ip = match[0]
			port = match[1]

	if ip is None:
		print("Incorrect IP-address")
		return 1

	print(f"Connecting to {ip}")

	from subprocess import call
	call([
		make_config.get_adb(), "disconnect"
	], stdout=devnull, stderr=devnull)
	call([
		make_config.get_adb(), "tcpip", port
	], stdout=devnull, stderr=devnull)
	result = call([make_config.get_adb(), "connect", ip])
	return result

@task("createProject")
def task_create_project():
	from project_manager import projectManager
	from project_manager_tasks import create_project

	try:
		index = create_project()
	except KeyboardInterrupt:
		return -1
	print("Project created!")

	try:
		r = input("Choice this project? [Y/n]: ")
	except KeyboardInterrupt:
		return -1
	if r.lower() != "n":
		projectManager.select_project(index = index)
		print(f"Project {index} selected")

	return 0

@task("removeProject")
def task_remove_project():
	from project_manager import projectManager
	if projectManager.how_much() == 0:
		error("Not found any project to remove.")

	try:
		who = projectManager.require_selection("Which project will be deleted?", "Do you really want to delete {}?", "I don't want it anymore")
	except KeyboardInterrupt:
		return -1
	if who is None:
		error("Deletion cancelled by user.")

	if projectManager.how_much() > 1:
		try:
			if input("Do you really want to delete it? [Y/n]: ").lower() == "n":
				error("Deletion cancelled by user.")
		except KeyboardInterrupt:
			return -1

	try:
		projectManager.remove_project(folder=who)
	except ValueError:
		error(f"""Folder "{who}" not found!""")

	print("Project permanently deleted.")
	return 0

@task("selectProject")
def task_select_project():
	from project_manager import projectManager
	if projectManager.how_much() == 0:
		error("Not found any project to select.")

	who = projectManager.require_selection("Which project do you choice?", "Do you want to select {}?")
	if who is None:
		error("Selection cancelled by user.")

	try:
		projectManager.select_project(folder=who)
	except ValueError:
		error(f"Folder {who} not found!""")

	print(f"Project {who} selected.")
	return 0

@task("updateToolchain")
def task_update_toolchain():
	from update import update
	update()
	return 0

@task("cleanup")
def task_cleanup():
	config = get_make_config()
	clear_directory(config.get_path("toolchain/build/gcc"))
	clear_directory(config.get_path("toolchain/build/gradle"))
	clear_directory(config.get_path("toolchain/build/project"))

	try:
		import java.java_build
		java.java_build.cleanup_gradle_scripts()
	except BaseException as err:
		print("Gradle cleanup skipped due to error:", err)
	return 0

def error(message, code=-1):
	sys.stderr.write(message + "\n")
	unlock_all_tasks()
	exit(code)


if __name__ == "__main__":
	if len(sys.argv[1:]) > 0:
		for task_name in sys.argv[1:]:
			if task_name in registered_tasks:
				try:
					result = registered_tasks[task_name]()
					if result != 0:
						error(f"task {task_name} failed with result {result}", code=result)
				except BaseException as err:
					if isinstance(err, SystemExit):
						raise err

					import traceback
					traceback.print_exc()
					error(f"Task {task_name} failed with above error")
			else:
				print(f"No such task: {task_name}")
	else:
		error("No tasks to execute.")
	unlock_all_tasks()