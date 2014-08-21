import docker, boto
from boto.s3.key import Key
import os, sys, time, gzip, isodate, datetime, pytz, tarfile, errno, sets

def log_info(s):
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    print (ts + "  " + s)
    sys.stdout.flush()

def esc_sessname(s):
    return s.replace("@", "_at_").replace(".", "_")

def read_config():
    with open("conf/tornado.conf") as f:
        cfg = eval(f.read())

    if os.path.isfile("conf/jbox.user"):
        with open("conf/jbox.user") as f:
            ucfg = eval(f.read())
        cfg.update(ucfg)

    cfg["admin_sessnames"]=[]
    for ad in cfg["admin_users"]:
        cfg["admin_sessnames"].append(esc_sessname(ad))

    cfg["protected_docknames"]=[]
    for ps in cfg["protected_sessions"]:
        cfg["protected_docknames"].append("/" + esc_sessname(ps))

    return cfg

def make_sure_path_exists(path):
    try:
        os.makedirs(path)
    except OSError as exception:
        if exception.errno != errno.EEXIST:
            raise

class JBoxContainer:
    CONTAINER_PORT_BINDINGS = {4200: ('127.0.0.1',), 8000: ('127.0.0.1',), 8998: ('127.0.0.1',)}
    HOST_VOLUMES = None
    DCKR = None
    PINGS = {}
    DCKR_IMAGE = None
    MEM_LIMIT = None
    PORTS = [4200, 8000, 8998]
    VOLUMES = ['/juliabox']
    LOCAL_TZ_OFFSET = 0
    BACKUP_LOC = None
    BACKUP_BUCKET = None
    S3_CONN = None

    def __init__(self, dockid):
        self.dockid = dockid
        self.refresh()

    def refresh(self):
        self.props = None
        self.dbgstr = None
        self.host_ports = None
   
    def get_props(self):
        if None == self.props:
            self.props = JBoxContainer.DCKR.inspect_container(self.dockid)
        return self.props
         
    def get_host_ports(self):
        if None == self.host_ports:
            props = self.get_props()
            ports = props['NetworkSettings']['Ports']
            port_map = []
            for port in JBoxContainer.PORTS:
                tcp_port = str(port) + '/tcp'
                port_map.append(ports[tcp_port][0]['HostPort'])
            self.host_ports = tuple(port_map)
        return self.host_ports

    def debug_str(self):
        if None == self.dbgstr:
            self.dbgstr = "JBoxContainer id=" + str(self.dockid) + ", name=" + str(self.get_name())
        return self.dbgstr
        
    def get_name(self):
        props = self.get_props()
        return props['Name'] if ('Name' in props) else None

    def get_image_names(self):
        props = self.get_props()
        img_id = props['Image']
        for img in JBoxContainer.DCKR.images():
            if img['Id'] == img_id:
                return img['RepoTags']
        return []
        
    @staticmethod
    def configure(dckr, image, mem_limit, host_volumes, backup_loc, backup_bucket=None):
        JBoxContainer.DCKR = dckr
        JBoxContainer.DCKR_IMAGE = image
        JBoxContainer.MEM_LIMIT = mem_limit
        JBoxContainer.LOCAL_TZ_OFFSET = JBoxContainer.local_time_offset()
        JBoxContainer.HOST_VOLUMES = host_volumes
        JBoxContainer.BACKUP_LOC = backup_loc
        if None != backup_bucket:
            JBoxContainer.S3_CONN = boto.connect_s3()
            JBoxContainer.BACKUP_BUCKET = JBoxContainer.S3_CONN.get_bucket(backup_bucket)

    @staticmethod
    def create_new(name):
        mount_point = os.path.join(JBoxContainer.BACKUP_LOC, name)
        if not os.path.exists(mount_point):
            os.makedirs(mount_point)
            os.chmod(mount_point, 0777)
        
        jsonobj = JBoxContainer.DCKR.create_container(JBoxContainer.DCKR_IMAGE, detach=True, mem_limit=JBoxContainer.MEM_LIMIT, ports=JBoxContainer.PORTS, volumes=JBoxContainer.VOLUMES, name=name)
        dockid = jsonobj["Id"]
        cont = JBoxContainer(dockid)
        log_info("Created " + cont.debug_str())
        cont.create_restore_file()
        return cont

    @staticmethod
    def launch_by_name(name, reuse=True):
        log_info("Launching container: " + name)

        cont = JBoxContainer.get_by_name(name)

        if (None != cont) and not reuse:
            cont.delete()
            cont = None

        if (None == cont):
            cont = JBoxContainer.create_new(name)

        if not cont.is_running():
            cont.start()

        return cont
    
    @staticmethod    
    def maintain(delete_timeout=0, stop_timeout=0, protected_names=[]):
        log_info("Starting container maintenance...")
        tnow = datetime.datetime.now(pytz.utc)
        tmin = datetime.datetime(datetime.MINYEAR, 1, 1, tzinfo=pytz.utc)

        delete_before = (tnow - datetime.timedelta(seconds=delete_timeout)) if (delete_timeout > 0) else tmin
        stop_before = (tnow - datetime.timedelta(seconds=stop_timeout)) if (stop_timeout > 0) else tmin

        all_containers = JBoxContainer.DCKR.containers(all=True)
        all_cnames = sets.Set()
        for cdesc in all_containers:
            cont = JBoxContainer(cdesc['Id'])
            cname = cont.get_name()
            all_cnames.add(cname)

            if (cname == None) or (cname in protected_names):
                log_info("Ignoring " + cont.debug_str())
                continue

            c_is_active = cont.is_running()
            last_ping = JBoxContainer.get_last_ping(cname)

            # if we don't have a ping record, create one (we must have restarted) 
            if (None == last_ping) and c_is_active:
                log_info("Discovered new container " + cont.debug_str())
                JBoxContainer.record_ping(cname)

            if cont.time_started() < delete_before:
                # don't allow running beyond the limit for long running sessions
                log_info("time_started " + str(cont.time_started()) + " delete_before: " + str(delete_before) + " cond: " + str(cont.time_started() < delete_before))
                log_info("Running beyond allowed time " + cont.debug_str())
                cont.delete()
            elif (None != last_ping) and c_is_active and (last_ping < stop_before):
                # if inactive for too long, stop it
                log_info("last_ping " + str(last_ping) + " stop_before: " + str(stop_before) + " cond: " + str(last_ping < stop_before))
                log_info("Inactive beyond allowed time " + cont.debug_str())
                cont.stop()

        # delete ping entries for non exixtent containers
        for cname in JBoxContainer.PINGS.keys():
            if cname not in all_cnames:
                del JBoxContainer.PINGS[cname]
                
        
        log_info("Finished container maintenance.")


    @staticmethod
    def push_to_s3(local_file, backup_time):
        if None == JBoxContainer.BACKUP_BUCKET:
            return None
        key_name = os.path.basename(local_file)
        k = Key(JBoxContainer.BACKUP_BUCKET)
        k.key = key_name
        k.set_metadata('backup_time', backup_time)
        k.set_contents_from_filename(local_file)
        return k
    
    @staticmethod
    def pull_from_s3(local_file, metadata_only=False):
        if None == JBoxContainer.BACKUP_BUCKET:
            return None
        key_name = os.path.basename(local_file)
        k = JBoxContainer.BACKUP_BUCKET.get_key(key_name)
        if (k != None) and (not metadata_only):
            k.get_contents_to_filename(local_file)
        return k

    @staticmethod
    def backup_all():
        log_info("Starting container backup...")
        all_containers = JBoxContainer.DCKR.containers(all=True)
        for cdesc in all_containers:
            cont = JBoxContainer(cdesc['Id'])
            cont.backup()

    def backup(self):
        log_info("Backing up " + self.debug_str() + " at " + str(JBoxContainer.BACKUP_LOC))
        cname = self.get_name()
        if cname == None:
            return

        bkup_file = os.path.join(JBoxContainer.BACKUP_LOC, cname[1:] + ".tar.gz")
        k = JBoxContainer.pull_from_s3(bkup_file, True)
        bkup_file_mtime = None
        if os.path.exists(bkup_file):
            bkup_file_mtime = datetime.datetime.fromtimestamp(os.path.getmtime(bkup_file), pytz.utc) + datetime.timedelta(seconds=JBoxContainer.LOCAL_TZ_OFFSET)
        elif None != k:
            bkup_file_mtime = JBoxContainer.parse_iso_time(k.get_metadata('backup_time'))

        if None != bkup_file_mtime:
            tstart = self.time_started()
            tstop = self.time_finished()
            tcomp = tstart if ((tstop == None) or (tstart > tstop)) else tstop
            if tcomp <= bkup_file_mtime:
                log_info("Already backed up " + self.debug_str())
                return

        bkup_resp = JBoxContainer.DCKR.copy(self.dockid, '/home/juser/')
        bkup_data = bkup_resp.read(decode_content=True)
        with gzip.open(bkup_file, 'w') as f:
            f.write(bkup_data)
        log_info("Backed up " + self.debug_str() + " into " + bkup_file)
        
        # Upload to S3 if so configured. Delete from local if successful.
        bkup_file_mtime = datetime.datetime.fromtimestamp(os.path.getmtime(bkup_file), pytz.utc) + datetime.timedelta(seconds=JBoxContainer.LOCAL_TZ_OFFSET)
        if None != JBoxContainer.push_to_s3(bkup_file, bkup_file_mtime.isoformat()):
            os.remove(bkup_file)
            log_info("Moved backup to S3 " + self.debug_str())


    def create_restore_file(self):
        cname = self.get_name()
        if cname == None:
            return
        
        src = os.path.join(JBoxContainer.BACKUP_LOC, cname[1:] + ".tar.gz")
        k = JBoxContainer.pull_from_s3(src)     # download from S3 if exists
        if not os.path.exists(src):
            return

        dest = os.path.join(JBoxContainer.BACKUP_LOC, cname[1:], "restore.tar.gz")
        log_info("Filtering out restore info from backup " + src + " to " + dest)

        src_tar = tarfile.open(src, 'r:gz')
        dest_tar = tarfile.open(dest, 'w:gz')
        for info in src_tar.getmembers():
            if info.name.startswith('juser/.') and not info.name.startswith('juser/.ssh'):
                continue
            if info.name.startswith('juser/resty'):
                continue
            info.name = info.name[6:]
            if len(info.name) == 0:
                continue
            dest_tar.addfile(info, src_tar.extractfile(info))
        src_tar.close()
        dest_tar.close()
        os.chmod(dest, 0666)
        log_info("Created restore file " + dest)

        # delete local copy of backup if we have it on s3
        if None != k:
            os.remove(src)

    @staticmethod
    def num_active():
        active_containers = JBoxContainer.DCKR.containers(all=False)
        return len(active_containers)

    @staticmethod
    def get_by_name(name):
        nname = "/" + unicode(name)

        for c in JBoxContainer.DCKR.containers(all=True):
            if ('Names' in c) and (c['Names'] != None) and (c['Names'][0] == nname):
                return JBoxContainer(c['Id'])
        return None

    @staticmethod
    def record_ping(name):
        JBoxContainer.PINGS[name] = datetime.datetime.now(pytz.utc)
        #log_info("Recorded ping for " + name)

    @staticmethod
    def get_last_ping(name):
        return JBoxContainer.PINGS[name] if (name in JBoxContainer.PINGS) else None

    @staticmethod
    def parse_iso_time(tm):
        if None != tm:
            tm = isodate.parse_datetime(tm)
        return tm

    @staticmethod
    def local_time_offset():
        """Return offset of local zone from GMT"""
        if time.localtime().tm_isdst and time.daylight:
            return time.altzone
        else:
            return time.timezone

    def is_running(self):
        props = self.get_props()
        state = props['State']
        return state['Running'] if 'Running' in state else False

    def time_started(self):
        props = self.get_props()
        return JBoxContainer.parse_iso_time(props['State']['StartedAt'])

    def time_finished(self):
        props = self.get_props()
        return JBoxContainer.parse_iso_time(props['State']['FinishedAt'])

    def time_created(self):
        props = self.get_props()
        return JBoxContainer.parse_iso_time(props['Created'])

    def stop(self):
        log_info("Stopping " + self.debug_str())
        self.refresh()
        if self.is_running():
            JBoxContainer.DCKR.stop(self.dockid)
            self.refresh()
            log_info("Stopped " + self.debug_str())
        else:
            log_info("Already stopped " + self.debug_str())

    def start(self):
        self.refresh()
        log_info("Starting " + self.debug_str())
        if self.is_running():
            log_info("Already started " + self.debug_str())
            return

        vols = {}
        for hvol,cvol in zip(JBoxContainer.HOST_VOLUMES, JBoxContainer.VOLUMES):
            hvol = hvol.replace('${CNAME}', self.get_name())
            vols[hvol] = {'bind': cvol, 'ro': False}

        JBoxContainer.DCKR.start(self.dockid, port_bindings=JBoxContainer.CONTAINER_PORT_BINDINGS, binds=vols)
        self.refresh()
        log_info("Started " + self.debug_str())
        cname = self.get_name()
        if None != cname:
            JBoxContainer.record_ping(cname)

    def kill(self):
        log_info("Killing " + self.debug_str())
        JBoxContainer.DCKR.kill(self.dockid)
        self.refresh()
        log_info("Killed " + self.debug_str())

    def delete(self):
        log_info("Deleting " + self.debug_str())
        self.refresh()
        cname = self.get_name()
        if self.is_running():
            self.kill()
        JBoxContainer.DCKR.remove_container(self.dockid)
        if cname != None:
            JBoxContainer.PINGS.pop(cname, None)
        log_info("Deleted " + self.debug_str())
        # remove mount point
        try:
            mount_point = os.path.join(JBoxContainer.BACKUP_LOC, cname[1:])
            os.rmdir(mount_point)
            log_info("Removed mount point " + mount_point)
        except:
            log_info("Error removing mount point " + self.debug_str())


dckr = docker.Client()
cfg = read_config()
backup_location = os.path.expanduser(cfg['backup_location'])
backup_bucket = cfg['backup_bucket']
make_sure_path_exists(backup_location)
JBoxContainer.configure(dckr, cfg['docker_image'], cfg['mem_limit'], [os.path.join(backup_location, '${CNAME}')], backup_location, backup_bucket=backup_bucket)
