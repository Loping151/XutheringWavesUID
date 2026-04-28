class WuWaCalc:
    pass

def reload_wuwacalc_module():
    global WuWaCalc
    try:
        from ..waves_build.wuwacalc import WuWaCalc as w
        WuWaCalc = w
        globals()["WuWaCalc"] = w
    except ImportError:
        return None

reload_wuwacalc_module()
