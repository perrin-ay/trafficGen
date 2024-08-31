# trafficGen

Written in sockets and epoll to provide granular control over generated sessions. Multiprocessing supported for heavy traffic loads. 

Author: Arnab Chatterjee

email: arnabchat21@gmail.com

---

**Features**
- The goal here is to provide a library to develop custom traffic patterns from layer 4 to layer 7 and be able to emulate any client traffic pattern found in packet captures.
- Asynchronous traffic generation using epoll and multiprocessing for scaling to high traffic loads
- Full TLS support
- Easily integrates scapy layers
- Optimized send() and recv() functions
- Logging and results of test
- Generate attacks to test application firewalls and WAFs
- **Extensively used in Radware RnD labs to recreate complex traffic scenarios and traffic related bugs**

---

**Examples**

See notebook for some usage examples
  
