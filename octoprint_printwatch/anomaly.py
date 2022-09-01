from enum import Enum

class States(Enum):
    OPEN_SERIAL = 0
    DETECT_SERIAL = 1
    DETECT_BAUDRATE = 2
    CONNECTING = 3
    OPERATIONAL = 4
    PRINTING = 5
    PAUSED = 6
    CLOSED = 7
    ERROR = 8
    CLOSED_WITH_ERROR = 9
    TRANSFERING_FILE = 10
    OFFLINE = 11
    UNKNOWN = 12
    NONE = 13

str1 = 'G0 F1200 X1 Y2'
str2 = 'G1 F1500.1 X5 Y8'


idx = str1.find('F')
idx1_end = str1.find(' ', idx)


idx2 = str2.find('F')
idx2_end = str2.find(' ', idx)


print(idx)
print(idx1_end)
print(str1[idx:idx1_end])
print(int(str1[idx+1:idx1_end]) > 1201)


print(idx2)
print(idx2_end)
print(str2[idx2:idx2_end])
print(float(str2[idx2+1:idx2_end]) > 1201)
#print(States['OFFLINE'].value)
