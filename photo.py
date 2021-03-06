#!/usr/bin/env python3

# Version 0.0.05

# Copyright (c) 2015 Patrik Fältström <paf@frobbit.se>
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation files
# (the "Software"), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify, merge,
# publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS
# BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
# ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import plistlib
import sqlite3
import getopt, sys
try:
    import applescript
except:
    print("You need a few Apple Libraries to make this to work")
    print(" ")
    print("Easiest way is to install with the help of pip3:")
    print(" ")
    print("# pip3 install py-applescript")
    print("# pip3 install PyObjC")
    print(" ")
    print("Note that you need pyobjc-core version 3.0.5 or later")
    print("See https://github.com/GreatFruitOmsk/pyobjc-core/releases/download/v3.0.5.dev0/pyobjc-core-3.0.5.tar.gz")
    sys.exit(1)

import re
from datetime import datetime
import time
import os.path
from os import listdir
from os.path import isfile, join

def usage():
    print("photo.py version 0.0.04")
    print("Arguments:")
    print(" -h --help           Gives help text")
    print(" -v --verbose        Verbose output")
    print(" -f FILE --file=FILE Looks for data in FILE (otherwise look for normal Photo library location)")
    print(" -r DIR --root=DIR   Store data in directory named DIR (otherwise in current working directory")
    print(" -i --init           Reinitialize database and files on disk")
    print(" SQLITEFILE          The sqlite database that holds data about the photo library")

verbose = False

# Dict with information about all photos
p = {}

# Dict with information about all persons/photos
pf = {}

# Set to version of database
theVersion = None

# Dicts with information about all files and folders on disk
theFiles = {}
theFolders = {}

# Root of where data is stored -- default is CWD
rootPath = ""

# The path to where photos are to be stored                                                                            
tmppath = "%s/tmp/" % rootPath
photopath = "%s/photos/" % rootPath

# Sqlite3 database with information about the photos                                                                   
photodb = "%s/photos.sqlite" % rootPath

photoconn = None
photoc = None

scptExport = ""
scptLaunch = ""
scptQuit = ""

# Handle progress bar (equivalent)
statusText = ""
maxValue = -1

def initStatus(text, max):
    global statusText
    global maxValue

    statusText = text
    maxValue = max

def setStatus(value):
    if(not verbose):
        if(maxValue > 0):
            progress = value / maxValue
            sys.stdout.write('\r%s: [ %-30s ] %3d%%' % (statusText, format('#' * int(progress * 30)), int(progress * 100)))
        else:
            sys.stdout.write('\r%s: %d' % (statusText, theNum))
        sys.stdout.flush()

def closeStatus():
    maxValue = -1
    statusText = ""
    if(not verbose):
        sys.stdout.write('\r%s: [ %-30s ] %d%%\n' % (statusText, format('#' * 30), 100))

# Various AppleScripts we need
def setupAppleScript():
    global scptExport
    global scptLaunch
    global scptQuit

    # Compile apple script that exports one image
    scptExport = applescript.AppleScript('''
        on run {arg}
          set thepath to "%s"
          tell application "Photos"
            set theitem to media item id arg
            set thelist to {theitem}
            export thelist to POSIX file thepath
          end tell
        end run
        ''' % (tmppath))
    
    # Compile apple script that launches Photos.App
    scptLaunch = applescript.AppleScript('''
        on run
          tell application "Photos"
            activate
          end tell
        end run
        ''')
    
    # Compile apple script that quits Photos.App
    scptQuit = applescript.AppleScript('''
        on run
          tell application "Photos"
            quit
          end tell
        end run
        ''')

# Epoch is Jan 1, 2001
td = (datetime(2001,1,1,0,0) - datetime(1970,1,1,0,0)).total_seconds()

def doLog(s):
    if(verbose):
        print(s)

def ensureDirectoryExists(thePath):
    if(not os.path.isdir(thePath)):
        os.mkdir(thePath)

def connectToPhotoDb():
    global photoconn
    global photoc
    global photodb
    if(photoconn != None):
        return()
    dbexists = False
    if(os.path.isfile(photodb)):
        dbexists = True
    try:
        photoconn = sqlite3.connect(photodb)
        photoc = photoconn.cursor()
    except:
        print("Could not connect to photdb %s" % photodb)
    if(not dbexists):
        # If the file did not exist, create the database
        photoc.execute('''CREATE TABLE photos (id integer primary key autoincrement,
                                               uuid text,
                                               filename text,
                                               shouldexist integer)''')
        photoc.execute('CREATE INDEX photos_uuid on photos (uuid)')
        photoconn.commit()
    try:
        photoc.execute('select * from settings')
    except:
        photoc.execute('''CREATE TABLE settings (id integer primary key autoincrement,
                                                 version integer,
                                                 rootpath text,
                                                 tmppath text,
                                                 photopath text,
                                                 filename text)''')
        photoconn.commit()
    return()

def checkWhatFilesExists():
    global theFiles
    theNum = 0
    theLen = len(photopath)
    initStatus("Files", 0)
    for root, dirs, files in os.walk(photopath, topdown=True):
        dirs[:] = [d for d in dirs if d not in [".jalbum"]]
        r = root[theLen:]
        if(not r in theFolders):
            theFolders[r] = False
        for f in files:
            theNum = theNum + 1
            setStatus(theNum)
            doLog('Found file %s in directory %s' % (f, r))
            thePath = "%s/%s" % (r, f)
            theFiles[thePath] = False
    closeStatus()

def maybeExport(p,uuid):
    global photoconn
    global photoc
    doLog("Checking uuid %s" % uuid)
    photoc.execute("SELECT count(*) FROM photos WHERE uuid = ?", (uuid,))
    number = photoc.fetchone()[0]
    if(number == 0):
        # Photo with this uuid does not exist, we think...
        # Create new record in database, and fetch what unique rowid was created
        photoc.execute('INSERT INTO photos VALUES (NULL, ?, "", 1)', (uuid,))
        photoconn.commit()
        photoc.execute("SELECT id FROM photos WHERE uuid = ?", (uuid,))
        theID = photoc.fetchone()[0]
        # Create the new filename based on rowid, and update the database
        theFilename = "IMG%07d.JPG" % (theID)
        photoc.execute('UPDATE photos SET filename = ? WHERE uuid = ?', (theFilename, uuid))
        photoconn.commit()
        # Export the file from Photos.app
        doLog("Trying to export %s" % (p[uuid]['filename']))
        thefiles = []
        while(len(thefiles) == 0):
            while(True):
                try:
                    scptExport.run(uuid)
                    break
                except applescript.ScriptError as e:
                    # Error -1728 is thrown if Photos.app is not ready yet
                    doLog("AppleScript Error %s" % e.number)
                    if(e.number != -1728):
                        raise
                    doLog("Photos.app not ready for export Apple Event")
                    time.sleep(0.5)
                    scptLaunch.run()
            # Check what filename it got (only one file in the directory)
            thefiles = [f for f in listdir(tmppath) if isfile(join(tmppath, f))]
            if(len(thefiles) > 1):
                doLog("There should be max one file in tmp, not %d" % len(thefiles))
                removeDirectory(tmppath)
                ensureDirectoryExists(tmppath)
                cleanup(p, uuid)
                return(False)
        thefile = thefiles[0]
        doLog("Exported photo with uuid %s to %s" % (uuid, thefile))
        if(thefile[-3:] != "JPG" and thefile[-3:] != "jpg"):
            print("The file extension is not JPG when exporting uuid %s to %s!" % (uuid, thefile))
            sys.exit(0)
        # Fetch first directory it should be stored in
        theTargetDirectory = p[uuid]['albums'][0]
        targetDir = "%s%s/" % (photopath, theTargetDirectory)
        os.makedirs(targetDir, exist_ok=True)
        targetPath = "%s%s" % (targetDir, theFilename)
        sourcePath = "%s%s" % (tmppath, thefile)
        # Move the file
        doLog("Stored as %s" % (targetPath))
        os.rename(sourcePath, targetPath)
        # Save info about the stored file
        theFiles["%s/%s" % (theTargetDirectory, theFilename)] = True
    # The file exist, at least in one location, fetch the filename (same in all directories)
    photoc.execute("SELECT filename FROM photos WHERE uuid = ?", (uuid,))
    theFilename = photoc.fetchone()[0]
    # Find one already exported version of the photo
    linkSource = None
    match = "/%s" % theFilename
    theLen = len(match)
    for k in theFiles.keys():
        if(k[-theLen:] == match):
            linkSource = k
            break
    if(not linkSource):
        doLog("Failed to find directory from file where filename = %s (UUID = %s)" % (theFilename, uuid))
        # Clean up database, file system will be cleaned up on next run
        photoc.execute("DELETE FROM photos WHERE uuid = ?", (uuid,))
        photoc.execute("DELETE from photos WHERE filename = ?", (theFilename,))
        photoconn.commit()
        doLog("Inconcistencies found [type 1 (%s, %s)]!" % (theFilename, uuid))
        return(False)
    linkSource = "%s%s" % (photopath, linkSource)
    # Loop over all directories (albums) the photo should exist in, and create hard links
    for theTargetDirectory in p[uuid]['albums']:
        # Check whether file exists
        if(not "%s/%s" % (theTargetDirectory, theFilename) in theFiles):
            # Create a hard link to already existing exported photo
            os.makedirs("%s%s" % (photopath, theTargetDirectory), exist_ok=True)
            linkTarget = "%s%s/%s" % (photopath, theTargetDirectory, theFilename)
            doLog("Linking %s" % linkTarget)
            try:
                os.link(linkSource, linkTarget)
            except:
                if(linkSource.lower() == linkTarget.lower()):
                    if(not verbose):
                        print("")
                    print("Two albums exists with same name, which must be corrected manually!")
                    print("%s" % linkSource)
                    print("%s" % linkTarget)
                    sys.exit(0)
                doLog("Link %s -> %s failed" % (linkSource, linkTarget))
                doLog("Unlink %s" % (linkTarget))
                os.unlink(linkTarget)
                doLog("Linking %s (2nd try)" % linkTarget)
                os.link(linkSource, linkTarget)
        # Update status of this path
        theFiles["%s/%s" % (theTargetDirectory, theFilename)] = True
        doLog("Validated %s/%s" % (theTargetDirectory, theFilename))
    return(True)

def checkWhatFoldersShouldExist():
    global theFolders
    for f in theFolders:
        if(len(f) > 0 and not theFolders[f]):
            doLog("Removing %s" % (f))
            removeDirectory("%s%s" % (photopath,f))

def checkPhotos():
    global photoconn
    global photoc
    global photodb
    i = 0
    ensureDirectoryExists(tmppath)
    ensureDirectoryExists(photopath)
    if(photoc == None):
        connectToPhotoDb()
        checkWhatFilesExists()
        checkWhatFoldersShouldExist()
    # Mark all photos as "not seen yet"
    photoc.execute('UPDATE photos SET shouldexist = 0')
    photoconn.commit()
    # Loop over all photos, one uuid at a time
    initStatus("Photos", len(p))
    for uuid in p:
        photoc.execute('UPDATE photos SET shouldexist = 1 WHERE uuid = ?', (uuid,))
        #photoconn.commit()
        setStatus(i)
        # Check export status etc
        if(not maybeExport(p,uuid)):
            maybeExport(p.uuid)
            print("\nSomething is seriously wrong with %s %s" % (p[uuid]['filename'], uuid))
            sys.exit(1)
        i = i + 1
    photoconn.commit()
    closeStatus()
    # Remove stuff that is not referenced
    # Start by checking photos table
    doLog("Look at things that is not referenced, remove those things")
    photoc.execute('SELECT filename FROM photos WHERE shouldexist = 0')
    for row in photoc.fetchall():
        match = "/%s" % row[0]
        theLen = len(match)
        doLog("Looking for filename %s" % row[0])
        for k in theFiles.keys():
            if(k[-theLen:] == match):
                # Tag files so that they later will be removed
                doLog("Tag %s for removal" % k)
                theFiles[k] = False
    # Remove the info about missing UUIDs
    photoc.execute('DELETE FROM photos WHERE shouldexist = 0')
    photoconn.commit()
    # Now look at the file table for stuff that should not exist
    for f in theFiles:
        if(not theFiles[f]):
            thePath = "%s%s" % (photopath, f)
            # Remove files that should not exist
            os.unlink(thePath)
            doLog("Removing %s" % (thePath))

def openLibrary(path,file):
    theFilename = "%s/Database/%s" % (path,file)
    if(not os.path.exists(theFilename)):
        theFilename = "%s/Database/apdb/%s" % (path,file)
    doLog("Trying to open database %s" % (theFilename))
    try:
        conn = sqlite3.connect("%s" % (theFilename))
        c = conn.cursor()
    except sqlite3.Error as e:
        print("An error occurred: %s %s" % (e.args[0],theFilename))
        sys.exit(3)
    doLog("SQLite database is open")
    return(conn, c)

def keepFolder(folder):
    global theFolders
    s = folder.find("/")
    while(s > 0):
        theFolders[folder[:s]] = True
        s = s + 1
        s = folder.find("/", s)
    theFolders[folder] = True

def doList(theFile):
    global p
    global pf

    # Ensure Photos.App is not running
    scptQuit.run()

    # Look for all combinations of persons and pictures
    doLog("Grabbing information about persons")
    (conn, c) = openLibrary(theFile,"Person.db")
    doLog("Have connection with database")
    i = 0
    c.execute("select count(*) from RKFace, RKPerson where RKFace.personID = RKperson.modelID")
    initStatus("Faces", c.fetchone()[0])
    c.execute("select RKPerson.name, RKFace.imageID from RKFace, RKPerson where RKFace.personID = RKperson.modelID")
    for person in c:
        if(not person[1] in pf):
            pf[person[1]] = []
        pf[person[1]].append(person[0])
        doLog("%s %s" % (person[1], person[0]))
        setStatus(i)
        i = i + 1
    conn.close()
    closeStatus()
    doLog("Finished walking through persons")

    doLog("Grabbing information about photos")
    (conn, c) = openLibrary(theFile,"Library.apdb")
    doLog("Have connection with database")
    d = conn.cursor()
    e = conn.cursor()
    c.execute("select count(*) from RKVersion, RKMaster where RKVersion.isInTrash = 0 and RKVersion.type = 2 and RKVersion.masterUuid = RKMaster.uuid and RKVersion.filename not like '%.pdf'")
    initStatus("Photos", c.fetchone()[0])
    c.execute("select RKVersion.uuid, RKVersion.modelId, RKVersion.masterUuid, RKVersion.filename, RKVersion.lastmodifieddate, RKVersion.imageDate, RKVersion.mainRating, RKVersion.hasAdjustments, RKVersion.hasKeywords, RKVersion.imageTimeZoneOffsetSeconds, RKMaster.imagePath from RKVersion, RKMaster where RKVersion.isInTrash = 0 and RKVersion.type = 2 and RKVersion.masterUuid = RKMaster.uuid and RKVersion.filename not like '%.pdf'")
    i = 0
    for row in c:
        setStatus(i)
        i = i + 1
        uuid = row[0]
        p[uuid] = {}
        p[uuid]['modelID'] = row[1]
        p[uuid]['masterUuid'] = row[2]
        p[uuid]['filename'] = row[3]
        try:
            p[uuid]['lastmodifieddate'] = datetime.fromtimestamp(row[4] + td)
        except:
            p[uuid]['lastmodifieddate'] = datetime.fromtimestamp(row[5] + td)
        p[uuid]['imageDate'] = datetime.fromtimestamp(row[5] + td)
        p[uuid]['mainRating'] = row[6]
        p[uuid]['hasAdjustments'] = row[7]
        p[uuid]['hasKeywords'] = row[8]
        p[uuid]['imageTimeZoneOffsetSeconds'] = row[9]
        p[uuid]['imagePath'] = row[10]
        p[uuid]['albums'] = []
        doLog("Fetching data for photo %s %s: %s" % (uuid,p[uuid]['filename'], p[uuid]['imageDate']))

        # Find what albums the picture is in:
        d.execute("select RKAlbum.name, RKAlbum.folderuuid from RKAlbum, RKVersion, RKAlbumVersion where RKVersion.modelId = RKAlbumVersion.versionId and RKAlbumVersion.albumId = RKAlbum.modelID and RKVersion.modelID = %d" % p[uuid]['modelID'])
        for albumrow in d:
            # Ignore album "Last Import" and albums named like "YYYY-MM" (the latter will be in Date folder)
            if(albumrow[0] != "Last Import" and (not re.match("^[0-9]{4}-[0-9]{2}$", albumrow[0]))):
                foldername = albumrow[0]
                folderUUID = albumrow[1]
                while(folderUUID != "LibraryFolder" and folderUUID != "TopLevelAlbums" and folderUUID != "TrashFolder"):
                    e.execute("select name, parentFolderUuid from RKFolder where uuid = \"%s\"" % folderUUID)
                    for folderrow in e:
                        doLog("folder: %s %s" % (folderrow[0], folderrow[1]))
                        foldername = "%s/%s" % (folderrow[0], foldername)
                        folderUUID = folderrow[1]
                p[uuid]['albums'].append("Albums/%s" % foldername)
                keepFolder("Albums/%s" % foldername)

        # Add folder name based on date of photo
        foldername = "Date/%s/%s" % (p[uuid]['imageDate'].strftime("%Y"), p[uuid]['imageDate'].strftime("%Y-%m"))
        p[uuid]['albums'].append(foldername)
        keepFolder(foldername)

        # Add folder name based on persons
        if(uuid in pf):
            for personName in pf[uuid]:
                p[uuid]['albums'].append("Persons/%s" % personName)
                keepFolder("Persons/%s" % personName)

        doLog("To be stored in album(s) %s" % (p[uuid]['albums']))
    conn.close()
    closeStatus()

def query_yes_no(question, default="no"):
    """Ask a yes/no question via raw_input() and return their answer.

    "question" is a string that is presented to the user.
    "default" is the presumed answer if the user just hits <Enter>.
        It must be "yes" (the default), "no" or None (meaning
        an answer is required of the user).

    The "answer" return value is True for "yes" or False for "no".
    """
    ## From http://stackoverflow.com/questions/3041986/python-command-line-yes-no-input
    ## ...but adopted to Python3
    valid = {"yes": True, "y": True, "ye": True, "no": False, "n": False}
    if default is None:
        prompt = " [y/n] "
    elif default == "yes":
        prompt = " [Y/n] "
    elif default == "no":
        prompt = " [y/N] "
    else:
        raise ValueError("invalid default answer: '%s'" % default)

    while True:
        sys.stdout.write(question + prompt)
        choice = input().lower()
        if default is not None and choice == '':
            return valid[default]
        elif choice in valid:
            return valid[choice]
        else:
            sys.stdout.write("Please respond with 'yes' or 'no' (or 'y' or 'n').\n")

def removeDirectory(directory):
    for root, dirs, files in os.walk(directory, topdown=False):
        for name in files:
            os.unlink(os.path.join(root, name))
            doLog("Removing %s" % (os.path.join(root, name)))
        for name in dirs:
            os.rmdir(os.path.join(root, name))
            doLog("Removing %s" % (os.path.join(root, name)))
    os.rmdir(directory)
    doLog("Removing %s" % (directory))

def reinitialize():
    global photodb
    global photopath
    global tmppath
    global rootpath
    if(len(rootpath) < 10):
        print("Rootpath is fishy..try again: %s" % rootpath)
        sys.exit(1)
    print("This will remove the following:")
    print("  %s" % photopath)
    print("  %s" % tmppath)
    print("  %s" % photodb)
    print(" ")
    response = query_yes_no("Are you 100% sure you want to reinitialize?")
    if(response):
        removeDirectory(photopath)
        removeDirectory(tmppath)
        doLog("Removing %s" % (photodb))
        os.unlink(photodb)
    else:
        sys.stdout.write("No reinitialization made\n")
    sys.exit(0)

def main():
    global verbose
    global tmppath
    global photopath
    global rootpath
    global photodb
    global theVersion

    #rootpath = CWD
    rootpath = os.getcwd()

    try:
        opts, args = getopt.getopt(sys.argv[1:], "hf:vir:", ["help", "file=", "verbose", "init", "root="])
    except getopt.GetoptError as err:
        # print help information and exit:
        print(err) # will print something like "option -a not recognized"
        usage()
        sys.exit(2)

    filename = ("%s/Pictures/Photos Library.photoslibrary" % os.path.expanduser("~"))
    if(not os.path.exists("%s/database/apdb/Library.apdb" % filename) and not os.path.exists("%s/database/Library.apdb" % filename)):
        filename = ("%s/Pictures/Photos_Library.photoslibrary" % os.path.expanduser("~"))
        if(not os.path.exists("%s/database/apdb/Library.apdb" % filename) and not os.path.exists("%s/database/Library.apdb" % filename)):
            filename = None
    
    if(len(args) > 1):
        usage()
        sys.exit(2)

    if(len(args) == 1):
        photodb = "%s/%s" % (os.getcwd(), args[0])
        connectToPhotoDb()
        photoc.execute("SELECT version, rootpath, tmppath, photopath, filename from settings")
        row = photoc.fetchone()
        if(row):
            theVersion = row[0]
            rootpath = row[1]
            tmppath = row[2]
            photopath = row[3]
            filename = row[4]

    # Patch until we know what arguments to use
    doInit = False
    for o, a in opts:
        if o in ("-v", "--verbose"):
            verbose = True
        elif o in ("-h", "--help"):
            usage()
            sys.exit(0)
        elif o in ("-r", "--root"):
            if(theVersion):
                print("Root path already set for this database")
                sys.exit(2)
            rootpath = a
        elif o in ("-f", "--file"):
            if(theVersion):
                print("Filename already set for this database")
                sys.exit(2)
            filename = a
            if(not os.path.exists("%s/database/apdb/Library.apdb" % filename) and not os.path.exists("%s/database/Library.apdb" % filename)):
                print("Database %s/database/[apdb/]Library.apdb does not exist" % filename)
                sys.exit(1)
        elif o in ("-i", "--init"):
            doInit = True
        else:
            assert False, "Unhandled option"    

    if(filename == None):
        print("No filename given")
        sys.exit(1)

    if(not theVersion):
        # The path to where photos are to be stored
        tmppath = "%s/tmp/" % rootpath
        photopath = "%s/photos/" % rootpath
        # Sqlite3 database with information about the photos
        photodb = "%s/photos.sqlite" % rootpath

    doLog("Using directory %s as root" % rootpath)
    doLog("Storing database as %s" % photodb)

    connectToPhotoDb()
    photoc.execute("SELECT version, rootpath, tmppath, photopath, filename from settings")
    row = photoc.fetchone()
    if(not row):
        doLog("Inserting values in the settings table")
        doLog("rootpath: %s" % rootpath)
        doLog("tmppath: %s" % tmppath)
        doLog("photopath: %s" % photopath)
        doLog("filename: %s" % filename)
        photoc.execute('INSERT INTO settings VALUES (NULL, ?, ?, ?, ?, ?)', (1, rootpath, tmppath, photopath, filename))
        photoconn.commit()

    setupAppleScript()

    if(doInit):
        reinitialize()
        sys.exit(0)

    doList(filename)
    checkPhotos()

if __name__ == "__main__":
    main()
