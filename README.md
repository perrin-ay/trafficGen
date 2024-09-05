# trafficGen

Written in sockets and epoll to provide granular control over generated traffic. Multiprocessing supported for heavy traffic loads. 

---

### Features

- The goal here is to provide a library to develop custom traffic patterns from layer 4 to layer 7 and be able to emulate any client traffic.
- Asynchronous traffic generation using epoll.
- Multiprocessing for scaling to high traffic loads
- Full TLS support
- Optimized send() and recv() functions
- Easily integrates scapy layers
- Logging and results of test
- Generate sophisticated attacks to test application firewalls and WAFs
- **Extensively used in Radware RnD labs to recreate complex traffic scenarios and traffic related field bugs**

---

### Usage

See notebook for some usage examples : https://github.com/perrin-ay/trafficGen/blob/main/Examples.ipynb
  
