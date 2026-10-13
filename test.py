# -*- coding: utf-8 -*-
import NXOpen

def main():
    theSession = NXOpen.Session.GetSession()
    lw = theSession.ListingWindow
    
    lw.SelectDevice(NXOpen.ListingWindow.DeviceType.Window, "")
    
    lw.Open()
    lw.WriteLine("Hello, World!")

if __name__ == '__main__':
    main()