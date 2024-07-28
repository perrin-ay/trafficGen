import socket, select
import logging
import logging.handlers
import time
import copy
import ssl
import binascii
import struct
import random
import multiprocessing as mp
import json
import os
import sys
import errno
import string



class WrtDiskProcess(object):
    def __init__(self,logger,mpq,directory,delim=',\n'):
        
        self.syncdict=mp.Manager().dict()
        self.syncdict['1']=1
        self.logger = logger
        self.mpq=mpq
        self.wrtdir=directory
        self.delim=delim
        self.writep=mp.Process(target=self._wrtng_to_disk)
        self.writep.daemon=True
        self.writep.start()
    
    def _wrtng_to_disk(self): 
        try:
            while self.syncdict['1']==1:        

                if self.mpq.empty() is False:
                    tmp=self.mpq.get()


                    fo=open(self.wrtdir,'a')
                    if os.stat(self.wrtdir).st_size >0:
                        fo.write(self.delim) 

                    json.dump(tmp, fo, sort_keys=True, indent=4, separators=(',', ': '),ensure_ascii=False)
                    fo.close() 

        except (IOError, UnicodeDecodeError, EOFError) as e:
                self.logger.debug('Exception caught in write to disk for results logging.Check error, if IO or EOF , then its fine since this writer process is deamon %s:%s.'%(str(type(e)),str(e)))
    
    def _terminate_writer(self):
        
        self.syncdict['1']=0
        if self.writep.is_alive():
            self.logger.debug('terminating write to disk process')
            self.writep.terminate()
            self.writep.join()
            self.logger.debug('results writer process %s'%str(self.writep))

class Client(object):
    
    def __init__(self, loglevel='INFO',log_disk='',log_console=True, sip=['10.107.246.199'],dip='10.107.246.23',dport=[80]):
        if loglevel:
            self.logger = log_setup(loglevel,log_disk,log_console)
        self.request={1:['GET / HTTP/1.1\r\nHost: 10.105.5.75\r\nConnection: keep-alive\r\nUser-Agent: Jakarta Commons-HttpClient/3.0.1\r\n\r\n']}
        self.connections=1
        self.tcpsessions=1
        self.asynctraffic=False
        self.sip=sip
        self.dip=dip
        self.dport=dport
        self.request_temp_index=1
        self.READ_ONLY = select.EPOLLIN | select.EPOLLPRI | select.EPOLLHUP | select.EPOLLERR
        self.READ_WRITE = self.READ_ONLY | select.EPOLLOUT
        self.WRITE_ONLY= select.EPOLLHUP | select.EPOLLERR|select.EPOLLOUT
        self.PEER_CLOSE = select.EPOLLHUP
        self.epoll_timer=0.1
        self.receive_timeout=0.1
        self.add_recv_tout_beforeclose = 0
        self.syn_timeout=3
        self.first_response_timeout=2
        self.estab_timeout=3
        self.empty_poll_timeout=5
        self.pipeline={'state':False}
        self.ssl=False
        self.sslv=int(ssl.PROTOCOL_TLSv1)
        self.cipher="HIGH:-aNULL:-eNULL"
        self.clientauth=False
        self.sslkey=''
        self.sslcert=''
        self.sni_hostname=None
        self.sockoptls=[]
        self.goal=None
        self.goal_max_process=4 

        self.cps=0
        self.dur=0
        self.simu=0
        self.semaphore=None


        self.sema_count=0
        self.want_results=False
        self.save_results=''
        os.system("taskset -p 0xff %d" % os.getpid()) 

        self.gracetime=1
        self.delayedsends=False
        self.http=False
        self._counters()

    @staticmethod
    def header_str(headdict):
        headerstr=''
        for i in headdict:
            tmp="%s%s %s"%(i,':',headdict[i])
            tmp+="\r\n"
            headerstr+=tmp
        return headerstr+"\r\n"   
  
    def results(self,save_results='ram',results_dir='', stats=False,keep_recvbuf=False,keep_sendbuf=True):
    
        self.want_results=True
        self.keep_recvbuf=keep_recvbuf
        self.keep_sendbuf=keep_sendbuf
        self.stats=stats
        if self.stats:
            self.respdurationidx={}
        self.results_queue=mp.Queue()
        self.save_results=save_results
        if self.save_results=='disk' and mp.cpu_count() >=2:
            pass
        else:
            self.save_results='ram'
            self.logger.debug('saving results has been set to ram per configuration or because minimum of 2 cores not found for results to disk')
        if self.save_results=='disk':
            self.diskwriter=WrtDiskProcess(self.logger, self.results_queue,results_dir)
            self.logger.debug('starting write to disk process')

    def _counters(self):
        self.totalfdconnections=mp.Value('i',0)
        self.totalfdclosures=mp.Value('i',0)                            
                
    
    def timer_options(self, **kwargs): 
        '''
        Available options and their preset values
        epoll_timer=0.1, receive_timeout=0.1,syn_timeout=3,estab_timeout=3,empty_poll_timeout=5,first_response_timeout=2
        '''
        if kwargs is not None:
            for key, value in kwargs.iteritems():
                if key=='epoll_timer':
                    self.epoll_timer=value
                    self.logger.debug('epoll_timer is %f'%self.epoll_timer)
                elif key=='receive_timeout':
                    self.receive_timeout=value
                    self.logger.debug('receive_timeout is %f'%self.receive_timeout)
                elif key=='syn_timeout':
                    self.syn_timeout=value
                    self.logger.debug('syn_timeout is %f'%self.syn_timeout)
                elif key=='estab_timeout':
                    self.estab_timeout=value
                    self.logger.debug('estab_timeout is %f'%self.estab_timeout)
                elif key=='empty_poll_timeout':
                    self.empty_poll_timeout=value
                    self.logger.debug('empty_poll_timeout is %f'%self.empty_poll_timeout)
                elif key=='first_response_timeout':
                    self.first_response_timeout=value
                    self.logger.debug('first_response_timeout is %f'%self.first_response_timeout)
                elif key=='add_recv_tout_beforeclose':
                    self.add_recv_tout_beforeclose=value
                    self.logger.debug('add_recv_tout_beforeclose is %f'%self.first_response_timeout)                 
        

    def ssl_options(self, **kwargs):
        '''
        ssl=False
        sslv=tlsv1
        cipher="HIGH:-aNULL:-eNULL"
        clientauth=False
        sslkey=''
        sslcert''
        
        '''
        if kwargs is not None:
            for key,value in kwargs.iteritems():
                if key=='ssl':
                    self.ssl=value
                if key=='sslv':
                    self.sslv=self._sslversion(str(value))
                if key=='cipher':
                    self.cipher=str(value)
                if key=='clientauth':
                    self.clientauth=value
                if key=='sslkey':
                    self.sslkey=str(value)
                if key=='sslcert':
                    self.sslcert=str(value)
                if key=='sni':
                    self.sni_hostname=str(value)
    
    def _sslversion(self,sslver):
        if sslver=='sslv23':
            finalvers=int(ssl.PROTOCOL_SSLv23)
        elif sslver=='tlsv1':
            finalvers=int(ssl.PROTOCOL_TLSv1)
        elif sslver=='sslv3':
            finalvers=int(ssl.PROTOCOL_SSLv3)
        elif sslver=='tlsv11':
            finalvers=int(ssl.PROTOCOL_TLSv1_1)
        elif sslver=='tlsv12':
            finalvers=int(ssl.PROTOCOL_TLSv1_2)
        else:
            finalvers=int(ssl.PROTOCOL_SSLv23)
        self.logger.debug('sslversion returned is %d and %s'%(finalvers,sslver))
        return finalvers
    
    def socket_options(self, sockoptls):
        self.sockoptls=sockoptls
        
    def request_options(self,**kwargs):        
        '''
        Available options and their preset values
        request={1:['GET / HTTP/1.1\r\nHost: 10.105.5.75\r\nConnection: keep-alive\r\nUser-Agent: Jakarta Commons-HttpClient/3.0.1\r\n\r\n']}
        hexstream=None
        pipeline=True
        '''
        if kwargs is not None:
            for key, value in kwargs.iteritems(): 

                if key=='request':
                    self.request=value
                elif key=='pipeline':
                    self.pipeline['state']=value
                elif key=='hexstream':
                    self.request=self._hexstream_convert(value)
                elif key=='cookieids':
                    self.cookieidents=value
                    self.http=True
                    self.yum=http(self.logger)
                    self.yum.cookies(cookieids=self.cookieidents)
                elif key=='cookieobject':
                    self.yum=value
                    
                    
        self.tcpsessions=len(self.request.keys())
        self.logger.debug('number of keys in request dictionary %d'%self.tcpsessions)
        self.logger.debug('request to be sent is %s'%self.request)
        self.logger.debug('pipeline is set to %s'%self.pipeline)                             
        
    def _hexstream_convert(self,stream):
        for key, value in stream.iteritems():
            templist=[]
            for v in value:
                templist.append(str(binascii.unhexlify(v)))
            stream[key]=templist
        self.logger.debug('converted hexstream %s'%str(stream))
        return stream
        
    def _cleanup(self,fd):
        self.totalfdclosures.value+=1
        self.logger.debug('closures count: %d'%self.totalfdclosures.value)
        
        if self.want_results and self.save_results:
            self.logger.debug('storing recv results triggered for %s'%str(str(fd)))
            self.results[fd]['responses'].append(self.recv_sockets[fd])
            self.results[fd]['sIP,sPort']=self.fd_sockets[fd].getsockname()
            if self.stats:
                self.results[fd]['responseslen'].append(self.recv_socketslen[fd])
            self.logger.debug('_cleanup for fd %s and connection %s'%(str(fd),str(self.results[fd]['sIP,sPort'])))
      
        self.logger.debug('_cleanup for fd %s'%(str(fd)))
        self.fd_sockets[fd].close()
        if self.want_results and self.stats:
            self.results[fd]['tot_sessiontime']=time.time()-self.connect_timer[fd]
        
        del self.fd_sockets[fd]
        del self.send_sockets[fd]
        del self.recv_socket_timer[fd]
        del self.recv_sockets[fd]
        del self.send_socket_timer[fd]
        if self.want_results and self.stats:
            del self.recv_socketslen[fd]
        del self.connect_timer[fd]
        self.epoll.unregister(fd)
  
    def _ssl_nonblock_handshake(self,fd):
        
        count=0
        while True:
            try:
                count=count+1
                self.fd_sockets[fd].do_handshake()
                self.ssl_hand[fd]=False
                break
            except ssl.SSLError as err:
                if err.args[0]==ssl.SSL_ERROR_WANT_READ:
                    self.epoll.modify(fd, select.EPOLLIN) 

                elif err.args[0] == ssl.SSL_ERROR_WANT_WRITE:
                    self.epoll.modify(fd, select.EPOLLOUT)
                else:
                    self.logger.debug('ssl exception raised %s'%str(err))
                    self.epoll.modify(fd, 0) 

                    self._cleanup(fd)
                    break
                    

        self.logger.debug('took %d calls for this ssl handshake'%count)
    
    def _socket_init_1(self):

        for _ in xrange(self.connections):
            
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if self.sockoptls:
                for sockopts in self.sockoptls:
                    exec(sockopts)
            
            s.bind((self.sip[random.randint(0,(len(self.sip)-1))], 0))
            s.setblocking(0)
            if self.ssl and self.sni_hostname=='random':
                self.sni_hostname=randomstring(5)
                
            if self.ssl and not self.clientauth:
                self.logger.debug('ssl without clientauth session for fd %s'%str(s.fileno()))
                ssl_sock=ssl.SSLSocket(s,server_side=False,ciphers=self.cipher, ssl_version=self.sslv, do_handshake_on_connect=False,server_hostname=self.sni_hostname)
            if self.ssl and self.clientauth:
                self.logger.debug('ssl with clientauth session for fd %s'%str(s.fileno()))
                if self.sslkey and self.sslcert:
                    ssl_sock=ssl.SSLSocket(s,server_side=False,ciphers=self.cipher, ssl_version=self.sslv, keyfile=self.sslkey, certfile=self.sslcert,do_handshake_on_connect=False,server_hostname=self.sni_hostname)
                else:
                    self.logger.debug('ssl with clientauth session but no key or cert provided for fd %s. reverting to ssl without clientauth'%str(s.fileno()))
                    ssl_sock=ssl.SSLSocket(s,server_side=False,ciphers=self.cipher, ssl_version=self.sslv,do_handshake_on_connect=False,server_hostname=self.sni_hostname)
            if self.ssl:
                self._socket_init_2(ssl_sock)
            else:
                self._socket_init_2(s)
               
            
    def _socket_init_2(self,sock):
            filenodict={}
            self.sockets.append(sock)
            self.fd_sockets[sock.fileno()]=sock
            self.logger.debug('request index value %d'%self.request_temp_index)
            self.send_sockets[sock.fileno()]=self.request[self.request_temp_index][:]
            if self.want_results and not self.keep_recvbuf:
                self.recv_sockets[sock.fileno()]=0
            else:    
                self.recv_sockets[sock.fileno()]=''
            if self.ssl:
                self.ssl_hand[sock.fileno()]=True
            else:
                self.ssl_hand[sock.fileno()]=False
            self.recv_socket_timer[sock.fileno()]=0
            self.send_socket_timer[sock.fileno()]=0
            self.pipeline[sock.fileno()]=0
            self.epoll.register(sock.fileno(), self.WRITE_ONLY)
            if self.want_results:
                if self.keep_sendbuf:
                    filenodict['requests']=self.send_sockets[sock.fileno()][:]
                else:
                    filenodict['requests']=[len(i) for i in self.send_sockets[sock.fileno()]]
                filenodict['responses']=[]    
                self.results[sock.fileno()]=copy.deepcopy(filenodict)
                if self.stats:
                    self.recv_socketslen[sock.fileno()]=0
                    self.respdurationidx[sock.fileno()]=0
                    filenodict['responseslen']=[]
                    filenodict['response_tot']=[0]*len(self.request[self.request_temp_index])
                    filenodict['response_first']=[]
                    filenodict['requestslen']=[len(i) for i in self.send_sockets[sock.fileno()]]
                    self.results[sock.fileno()]=copy.deepcopy(filenodict)
                
                
            self.request_temp_index+=1
            if not (self.request_temp_index in self.request.keys()):
                self.request_temp_index=1
                self.logger.debug('request index initialized back to 1')
            
    def send_delays(self,delaysls={}):
        self.delayedsends=True
        self.delaysls=delaysls
        if not len(self.request)==1:
            self.logger.debug('delayed sends only valid when request is configured with one connection')
            sys.exit(0)
        if not len(self.request[1])==len(self.delaysls[1]):
            self.logger.debug('delays are not equal to number of requests')
        self.logger.debug('delayed sends object is set, it will only be used when traffic is not asynchronous and not goal defined')
        


    def _connect(self):
        for s in self.sockets:
            try:
                self.connect_timer[s.fileno()]=time.time()
                             
                s.connect((self.dip,self.dport[random.randint(0,(len(self.dport)-1))]))
            except socket.error as e:
                self.logger.debug('pid %s :connect returned %s'%(str(os.getpid()),str(e[1])))
        eventsrefresh=time.time()
        return eventsrefresh
   
    def goal_driven(recv_func):
        def wrapper(self):
            if self.goal in ['cps','simu']:
                self.logger.debug('goal selected is %s'%self.goal)
                self.semaphore=mp.BoundedSemaphore(self.goal_max_process) 

                if self.goal=='cps':
                    tend=time.time() + self.dur
                    proclist=[]
                    
                    

                    

                    

                    
                    while time.time() <=tend:
                        for conn in self.cps_map: 

                            self.semaphore.acquire() 

                            

                            self.shared_sema_count.value+=1
                            self.logger.debug('sema acquired')
                            self.logger.debug('sema manual count %s'%str(self.shared_sema_count.value))
                            self.connections=conn
                            p = mp.Process(target=recv_func, args=(self,)) 
                            p.daemon=True
                            p.start()
                            self.totalfdconnections.value+=conn
                        time.sleep(self.cps_interval)
                        self.logger.debug('cps interval elapsed!!!!')
                    self.logger.debug('test duration has elapsed')
                    

                    
            else:
                self.logger.debug('no goal selected, send %d connections'%int(self.connections))
                if self.asynctraffic:
                    self.totalfdconnections.value+=self.connections
                else:
                    self.totalfdconnections.value+=self.tcpsessions
                r=recv_func(self) 
                if self.want_results and self.save_results=='disk':
                    self.logger.debug('calling terminate writer')
                    self.diskwriter._terminate_writer()    
                elif self.want_results and self.save_results=='ram' :
                    return r

            

        return wrapper



    @goal_driven
    def generate(self):
        self.epoll = select.epoll()
        self.sockets=[]
        self.fd_sockets={}
        self.send_sockets={}
        self.recv_sockets={}
        self.recv_socketslen={}
        self.ssl_hand={}
        self.send_socket_timer={}
        self.recv_socket_timer={}
        self.connect_timer={}
        self.results={}
        self.seqtrafficresultsdict={}
        if self.want_results and self.stats:
            self.results['ConnError']={'event25':0,'event28':0, 'event20':0, 'established_timeout_firstresp':0,'established_timeout':0,'syn_timeout':0}
        if self.tcpsessions >0 and self.asynctraffic == False:
            self.logger.debug('sequentially generated traffic for requests struct')
            for indx in xrange(self.tcpsessions):
                self.request_temp_index= indx +1
                self.logger.debug('request dictionary key %s will be requested'%str(self.request_temp_index))
                self._socket_init_1()
                eventsrefresh=self._connect()
                self._main_event_loop(eventsrefresh)
                self.seqtrafficresultsdict[indx]=self.results
                self.epoll = select.epoll()
                self.sockets=[]
                self.fd_sockets={}
                self.send_sockets={}
                self.recv_sockets={}
                self.recv_socketslen={}
                self.ssl_hand={}
                self.send_socket_timer={}
                self.recv_socket_timer={}
                self.connect_timer={}
                self.results={}
                
                if self.want_results and self.stats:
                    self.results['ConnError']={'event25':0,'event28':0, 'event20':0, 'established_timeout_firstresp':0,'established_timeout':0,'syn_timeout':0}
        else:
            self._socket_init_1()
            eventsrefresh=self._connect()
            self._main_event_loop(eventsrefresh)
        if self.want_results and self.stats:
            
            self.results['total_openconnections']=self.totalfdconnections.value
            self.results['total_closedconnection']=self.totalfdclosures.value
            

            
        if not self.goal and self.save_results=='disk' and self.want_results:
            

            if self.asynctraffic:
                self.logger.debug('No goals set but asynctraffic. adding full dict to shared queue for writing')
                self.results_queue.put(self.results)
            else:
                self.logger.debug('No goals and no asynctraffic. adding dict of sequential connections to shared queue for writing')
                self.results_queue.put(self.seqtrafficresultsdict)
            


            
        if self.semaphore:
            if self.want_results and self.save_results:
                self.logger.debug('adding results to shared queue')
                self.results_queue.put(self.results)
            self.logger.debug('releasing sema')
            self.semaphore.release()
            self.shared_sema_count.value-=1
            self.logger.debug('sema_manual_count %s'%str(self.shared_sema_count.value))
        if not self.goal and self.save_results=='ram' and self.want_results:
            if self.asynctraffic:
                return self.results
            else: 
                return self.seqtrafficresultsdict
        

        if self.goal or self.save_results=='disk':
            time.sleep(self.gracetime) 

        
        
        
    def _main_event_loop(self,eventsrefresh):
        self.logger.debug( 'pid %s: fd_sockets %s'% (str(os.getpid()),str(self.fd_sockets)))
        while self.fd_sockets:
            self.logger.debug( 'pid %s: fd_sockets %s'% (str(os.getpid()),str(self.fd_sockets)))
            self.logger.debug( 'pid %s: recv_socket_timer %s'% (str(os.getpid()),str(self.recv_socket_timer)))
            self.logger.debug('pid %s: send_socket_timer %s'% (str(os.getpid()),str(self.send_socket_timer)))
            

            for ct in self.connect_timer.items():
                if time.time()-ct[1] >self.syn_timeout and self.send_socket_timer[ct[0]]==0:
                    self.logger.debug('pid %s: Timer expire for socket fd %s. TCP handshake didnt complete in required time.'%(str(os.getpid()),str(ct[0])))
                    self.epoll.modify(ct[0], 0)
                    if self.want_results and self.stats:
                        self.results['ConnError']['syn_timeout']+=1
                    self._cleanup(ct[0])

            

            for sn in self.send_socket_timer.items():

                if sn[1] >0 and time.time()-sn[1] >self.estab_timeout and self.recv_socket_timer[sn[0]]==0:

                    
                    self.logger.debug('pid %s: send timer expire-first response, for socket fd %s'%(str(os.getpid()),str(sn[0])))
                    if self.want_results and self.stats:
                        self.results['ConnError']['established_timeout_firstresp']+=1
                    self.epoll.modify(sn[0], 0)
                    self._cleanup(sn[0])
                elif sn[1] >0 and time.time()-sn[1] >self.estab_timeout and self.recv_socket_timer[sn[0]]>0:
                    self.logger.debug('pid %s: send timer expire- established connection, for socket fd %s'%(str(os.getpid()),str(sn[0])))
                    if self.want_results and self.stats:
                        self.results['ConnError']['established_timeout']+=1
                    self.epoll.modify(sn[0], 0)
                    
                    self._cleanup(sn[0])
                    

            

            

            for t in self.recv_socket_timer.items():
                if t[1]==0:
                    pass
                elif time.time()-t[1] >self.receive_timeout: 

                    if  self.pipeline[t[0]] <= (len(self.send_sockets[t[0]])-1):
                        self.logger.debug('pid %s: moving socket fd %s to OUT event after receive timer elapse' %(str(os.getpid()),str(t[0])))      
                        if self.want_results:
                            self.results[t[0]]['responses'].append(self.recv_sockets[t[0]])
                            if self.stats:
                                self.results[t[0]]['responseslen'].append(self.recv_socketslen[t[0]])
                                self.recv_socketslen[t[0]]=0
                        if self.want_results and not self.keep_recvbuf:
                            self.recv_sockets[t[0]]=0
                        else:    
                            self.recv_sockets[t[0]]=''
                        self.epoll.modify(t[0], select.EPOLLOUT)
                    else:
                        self.logger.debug('pid %s: receive timeout for %s expired at %s=%s-%s'%(str(os.getpid()),str(t[0]),str(time.time()-t[1]),str(time.time()),str(t[1])))
                        time.sleep(self.add_recv_tout_beforeclose)
                        self.epoll.modify(t[0], 0)

                        self._cleanup(t[0])



            events = self.epoll.poll(self.epoll_timer)
            self.logger.debug('pid %s: polled events %s'%(str(os.getpid()),(events)))
            if events:
                eventsrefresh=time.time()
            elif time.time()-eventsrefresh >self.empty_poll_timeout: 

                self.logger.debug('pid %s: epoll events have been null for %s'%(str(os.getpid()),str(time.time()-eventsrefresh)))
                self.logger.debug('pid %s: clearing all sockets and breaking from event loop'%(str(os.getpid())))
                for clean in self.fd_sockets.items():
                    try:
                        self.epoll.modify(clean[0], 0) 

                        self._cleanup(clean[0])
                        
                    except Exception as e:

                        self.logger.debug('exception raised in clean func %s'%str(e))
                break

            for fileno, event in events:
                self.logger.debug('pid %s: fileno %s , event %s'%(str(os.getpid()),fileno, event))
                

                if self.want_results and self.stats:
                    self.logger.debug('printing want results and stats %s %s'%(str(self.want_results),str(self.stats)))
                    try:
                        if 'dIP,dPort' in self.results[fileno].keys():
                           pass
                        else:
                            self.results[fileno]['dIP,dPort']=self.fd_sockets[fileno].getpeername()
                    except socket.error as e:
                        self.logger.debug('exception raised while getting peer name stat. This might when peer rsts connection %s:%s'%(str(type(e)),str(e)))
                
                if event==20:
                    self.logger.debug('socket fd %s is with event 20.'%(str(fileno)))
                    self.logger.debug('pid %s: clearing socket data structure for fd %s'%(str(os.getpid()),str(fileno)))
                    if self.want_results and self.stats:
                        self.results['ConnError']['event20']+=1
                    self.epoll.modify(fileno, 0)  

                    self._cleanup(fileno)
                    
                

                elif event==28:
                    self.logger.debug('socket fd %s errored with event 28. This can happen if TCP handshake was not successful'%(str(fileno)))
                    self.logger.debug('pid %s: clearing socket data structure for fd %s'%(str(os.getpid()),str(fileno)))
                    if self.want_results and self.stats:
                        self.results['ConnError']['event28']+=1
                    self.epoll.modify(fileno, 0)  

                    self._cleanup(fileno)
                

                elif event==25:
                    self.logger.debug('socket fd %s errored with event 25. This can happen when FIN/RST is sent from peer'%(str(fileno)))
                    self.logger.debug('pid %s: clearing socket data structure for fd %s'%(str(os.getpid()),str(fileno)))
                    if self.want_results and self.stats:
                        self.results['ConnError']['event25']+=1
                    self.epoll.modify(fileno, 0)  

                    self._cleanup(fileno)

                elif event & select.EPOLLOUT: 

                    if self.ssl_hand[fileno]:
                        self.logger.debug('pid %s: socket %s is in epollout event for ssl handshake'%(str(os.getpid()),str(fileno)))
                        self._ssl_nonblock_handshake(fileno)
                        
                    try:
                        if not self.asynctraffic and not self.goal and self.delayedsends:
                            try:
                                self.logger.debug('delayed send sleep for %s seconds'%str(self.delaysls[1][self.pipeline[fileno]]))
                                time.sleep(self.delaysls[1][self.pipeline[fileno]])
                            except Exception as e:
                                self.logger.debug('delayedsend exception raised %s:%s'%(str(type(e)),str(e)))
                        

                        if self.send_socket_timer[fileno]==0:
                            self.send_socket_timer[fileno]=time.time()
                        if self.pipeline[fileno] <=  len(self.send_sockets[fileno])-1:
                            self.logger.debug('pid %s: sending request list index is %d'%(str(os.getpid()),self.pipeline[fileno]))

                            try:
                                if not self.asynctraffic and not self.goal and self.http and self.yum.cookie and self.yum.cookiejar:
                                    self.send_sockets[fileno][self.pipeline[fileno]]=self.yum._addcookie(self.send_sockets[fileno][self.pipeline[fileno]])
                                byteswritten = self.fd_sockets[fileno].send(self.send_sockets[fileno][self.pipeline[fileno]])
                                self.send_socket_timer[fileno]=time.time()
                                self.send_sockets[fileno][self.pipeline[fileno]]=self.send_sockets[fileno][self.pipeline[fileno]][byteswritten:]



                                if len(self.send_sockets[fileno][self.pipeline[fileno]]) == 0:


                                    if self.pipeline['state'] and (self.pipeline[fileno] < (len(self.send_sockets[fileno])-1)):
                                        self.pipeline[fileno]=self.pipeline[fileno]+1
                                        self.send_socket_timer[fileno]=0
                                        self.logger.debug('pid %s: request list index incremented to %d'%(str(os.getpid()),self.pipeline[fileno]))
                                    else:
                                        self.pipeline[fileno]=self.pipeline[fileno]+1
                                        self.logger.debug('pid %s: request list index incremented to %d and poll state changed to receive traffic for fd %s'%(str(os.getpid()),self.pipeline[fileno], str(fileno)))
                                        self.recv_socket_timer[fileno]=time.time()
                                        self.epoll.modify(fileno,select.EPOLLIN)
                            except Exception as e:
                                self.logger.debug('send exception raised %s:%s'%(str(type(e)),str(e)))
                                self.logger.debug('cleaning socket')
                                self.epoll.modify(fileno, 0) 

                                self._cleanup(fileno)
                        else:
                            self.logger.debug('end of request list has been reached, moving to epollin')
                            self.epoll.modify(fileno,select.EPOLLIN)
                    except (ssl.SSLError, ssl.SSLEOFError,KeyError) as err:
                        if err.args[0] == ssl.SSL_ERROR_WANT_READ:
                            self.logger.debug('pid %s: ssl handshake error want read for %s. modify epoll to recv'%(str(os.getpid()),fileno))
                            self.epoll.modify(fileno, select.EPOLLIN)
                        elif err.args[0] == ssl.SSL_ERROR_WANT_WRITE:
                            self.logger.debug('pid %s: ssl handshake error want write for %s. modify epoll to write'%(str(os.getpid()),fileno))
                            self.epoll.modify(fileno, select.EPOLLOUT)
                        elif err.args[0] == 8:
                            self.logger.debug('pid %s: ssl exception raised %s'%(str(os.getpid()),str(err)))
                            try:
                                self.epoll.modify(fileno, 0) 

                                self._cleanup(fileno)
                            except IOError as e:
                                self.logger.debug('ssl exception 8 raised keyerror- sort of band aid exception handling %s'%(str(e)))
                                
                        else:
                            self.logger.debug('band aid solution to catch keyerror for unsuccessfull ssl handshake %s'%(str(err)))
                            pass
                            
                            
                elif event & select.EPOLLIN:
                    try:
                        

                        firstbytedelta=0
                        finalbytedelta=0
                        self.recv_socket_timer[fileno]=time.time()
                        if self.want_results and self.keep_recvbuf:
                            recvlen=len(self.recv_sockets[fileno])
                        elif self.want_results and not self.keep_recvbuf:
                            recvlen=self.recv_sockets[fileno]
                        if self.want_results and self.stats and recvlen==0:
                            self.respdurationidx[fileno]+=1
                            firstbytedelta=self.recv_socket_timer[fileno]-self.send_socket_timer[fileno]
                            self.results[fileno]['response_first'].append(firstbytedelta)
                            self.results[fileno]['response_tot'][self.respdurationidx[fileno]-1]=firstbytedelta 

                        elif self.want_results and self.stats and recvlen > 0:
                            finalbytedelta= self.recv_socket_timer[fileno]-self.send_socket_timer[fileno]  
                            self.results[fileno]['response_tot'][self.respdurationidx[fileno]-1]=finalbytedelta  
                            
                        try:
                            tmprecv=self.fd_sockets[fileno].recv(8192)
                            self.logger.debug('READ %d bytes'%len(tmprecv))
                            

                            

                            if len(tmprecv) <=0:
                                self.logger.debug('closing socket due to likely recive of closure from peer')
                                self.epoll.modify(fileno, 0)
                                self._cleanup(fileno)
                            else:
                                if not self.asynctraffic and not self.goal and self.http and self.yum.cookie:
                                    self.yum._parseresponse(tmprecv[:self.yum.parselen])
                                if self.want_results and not self.keep_recvbuf:
                                    self.logger.debug('pid %s: flashing recv buf'%(str(os.getpid())))
                                    self.recv_sockets[fileno] += len(tmprecv)
                                    self.logger.debug('pid %s: print length of received data %d' %(str(os.getpid()),self.recv_sockets[fileno]))
                                    if self.stats:
                                        self.logger.debug('recv socket len %d'%self.recv_socketslen[fileno])
                                        self.recv_socketslen[fileno]=self.recv_sockets[fileno]
                                else:
                                    self.recv_sockets[fileno] += tmprecv
                                    if self.want_results and self.stats:
                                        self.recv_socketslen[fileno]=len(self.recv_sockets[fileno])
                                    self.logger.debug('pid %s: print length of received data %d' %(str(os.getpid()),len(self.recv_sockets[fileno])))

                        
                        except (IOError, KeyError) as e:
                            if str(type(e))=="""<type 'exceptions.KeyError'>""":
                                self.logger.debug ("""<type 'exceptions.KeyError'>""")
                                self.logger.debug('exception raised %s:%s'%(str(type(e)),str(e)))
                            elif e.errno == errno.EWOULDBLOCK:
                                self.logger.debug('errno: %s'%str(e.errno))
                                self.logger.debug('pid %s: error11, trying to read recv but found nothing'%str(os.getpid()))
                                                        
                        

                    except ssl.SSLError as err:
                        if err.args[0] == ssl.SSL_ERROR_WANT_READ:
                            self.logger.debug('pid %s: ssl handshake error want read for %s. modify epoll to recv'%(str(os.getpid()),fileno))
                            self.epoll.modify(fileno, select.EPOLLIN)
                        elif err.args[0] == ssl.SSL_ERROR_WANT_WRITE:
                            self.logger.debug('pid %s: ssl handshake error want write for %s. modify epoll to write'%(str(os.getpid()),fileno))
                            self.epoll.modify(fileno, select.EPOLLOUT)
                        else:
                            self.logger.debug('pid %s: ssl exception raised %s'%(str(os.getpid()),str(os.getpid()),str(err)))
                            self.epoll.modify(fileno, 0) 

                            self._cleanup(fileno)
                            

                
                elif event & select.EPOLLHUP:
                    self.logger.debug('pid %s: hangup occured on  %s '%(str(os.getpid()),str(self.fd_sockets[fileno])))
                    self.logger.debug('pid %s: hangup event logged on  %s '%(str(os.getpid()),str(event)))
                    self.epoll.modify(fileno, 0) 

                    self._cleanup(fileno)

                
                elif event & select.EPOLLRDHUP:
                    self.logger.debug('pid %s: rdhangup occured on  %s '%(str(os.getpid()),str(self.fd_sockets[fileno])))
                    self.logger.debug('pid %s:rdhangup event logged on  %s '%(str(os.getpid()),str(event)))
                    self.epoll.modify(fileno, 0) 

                    self._cleanup(fileno)
                    
                
                
                elif event & select.EPOLLERR:
                    self.logger.debug('pid %s: epollerr occured on  %s '%(str(os.getpid()),str(self.fd_sockets[fileno])))
                    try:

                        self.epoll.modify(fileno, 0) 

                        self._cleanup(fileno)

                        

                    except Exception as e:
                        self.logger.debug('exception occured when trying to clean epollerred socket with exception %s'% str(e))
                        self._cleanup(fileno)
                        
                elif self.fd_sockets:
                    continue
                else:
                    break  
    
class AsyncClient(Client):

    def __init__(self, loglevel='INFO',log_disk='',log_console=True,connections=5,sip=['10.107.246.199'],dip='10.107.246.23',dport=[80]):
        super(AsyncClient, self).__init__(loglevel=loglevel,log_disk=log_disk, log_console=log_console, sip=sip, dip=dip,dport=dport)
        self.connections=connections
        self.asynctraffic=True 

    def objective(self, goal='cps', cps=None, dur=10, simu=None,goal_max_cores=mp.cpu_count()-1):
        self.goal=goal
        self.goal_max_process=goal_max_cores
        assert (self.goal_max_process <= mp.cpu_count()),"Exiting ...Number of cores selected is more than available on the machine" 
        self.cps=cps
        self.dur=dur
        self.simu=simu
        self.shared_sema_count=mp.Value('i', 0)
        self.cps_interval=1
        self.daemon_exit_delay=self.estab_timeout
        if self.cps:
            self.cps_map=Estimator().cps_estimator(self.cps)
        self.logger.debug('cps_map: %s'%str(self.cps_map))
        self.logger.debug('objective invoked goal : %s'%str(self.goal))
        self.logger.debug('objective parameters: %s, %s, %s, %s'%(str(self.goal_max_process),str(self.cps),str(self.simu),str(self.dur)))

class Estimator(object): 

    def __init__(self):
        self.cpu=mp.cpu_count()
        self.cps_per_cpu=200
        
    def cps_estimator(self, cps):
        cps_map=[]
        self.desired_cps=cps
        if self.desired_cps > self.cps_per_cpu:
            
            self.cpu_per_sec=self.desired_cps/self.cps_per_cpu
            for _ in xrange(self.cpu_per_sec):
                cps_map.append(self.cps_per_cpu)
            if self.desired_cps%self.cps_per_cpu >0:
                self.cpu_per_sec+=1
                cps_map.append(self.desired_cps%self.cps_per_cpu)
        else:
            cps_map.append(self.desired_cps)
        return cps_map

class http(object):
    def __init__(self, logger):
        self.logger=logger
        self.cookie=False
  
    def cookies(self, cookieids=[],parselen=256):
        self.cookieids=cookieids
        if len(self.cookieids)>0:
            self.cookie=True
        self.parselen=parselen
        self.cookiejar={}
    
    def _bake(self):
        if self.cookiejar:
            bakestring='Cookie: '
            for c,b in enumerate(self.cookiejar):
                tmpbake=b+'='+self.cookiejar[b]
                if c+1==len(self.cookiejar):
                    bakestring+=tmpbake+'\r\n'
                else:
                    bakestring+=tmpbake +';'
            return bakestring
        else:
            return ''
                
    def _addcookie(self,request):
        if request:
            firstidx=request.find('HTTP/1.1\r\n')+10
            return request[:firstidx]+self._bake()+request[firstidx:]
        else:
            return ''
    
    def _parseresponse(self,pay):
        if self.cookie:
            if self.cookieids:
                for c in self.cookieids:
                    idx=pay.find('Set-Cookie: '+c)
                    if idx >=0:
                        idxequal=idx+12+len(c)
                        if pay.find(';',idx+12+len(c))>=0:
                            idxend=min(pay.find(';',idx+12+len(c)),pay.find('\r\n',idx+12+len(c)))
                        else:
                            idxend=pay.find('\r\n',idx+12+len(c))
                        self.cookiejar[c]=pay[idxequal+1:idxend]
            self.logger.debug('contents of cookie jar after respose parse %s'%str(self.cookiejar))        
        
    
def log_setup(loglvl,write_file,print_console):
    logger = logging.getLogger('myLogger')
    formatter=logging.Formatter('%(asctime)s %(name)s %(process)d %(message)s')
    if write_file:
        filehandler=logging.FileHandler(write_file)
        filehandler.setFormatter(formatter)
        logger.addHandler(filehandler)
    if print_console:
        streamhandler=logging.StreamHandler()
        streamhandler.setFormatter(formatter)
        logger.addHandler(streamhandler)


    if loglvl=='DEBUG':
        logger.setLevel(logging.DEBUG)
        return logger
    else:
        logger.setLevel(logging.INFO)
        return logger
    
def randomstring(length):
    return ''.join(random.choice(string.lowercase) for i in range(length))



