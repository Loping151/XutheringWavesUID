from gsuid_core.logger import logger


class WuWaCalc:
    """占位类。真类来自 waves_build.wuwacalc，由 reload_wuwacalc_module 注入。"""

    def __new__(cls, *args, **kwargs):
        # 走到占位类说明此前 reload 未成功，主动再补一次
        if reload_wuwacalc_module():
            real = globals()["WuWaCalc"]
            if real is not cls:
                return real(*args, **kwargs)
        raise RuntimeError(
            "[鸣潮] WuWaCalc 真类加载失败，请查看日志中 reload_wuwacalc_module 的报错"
        )


def resolve_node_state(role_detail):
    try:
        from ..waves_build.wuwacalc import resolve_node_state as f
    except Exception:
        return {}
    return f(role_detail)


def reload_wuwacalc_module():
    global WuWaCalc
    try:
        from ..waves_build.wuwacalc import WuWaCalc as w
    except Exception as e:
        logger.error(f"[鸣潮·伤害计算] reload_wuwacalc_module 失败: {type(e).__name__}: {e}")
        return False
    WuWaCalc = w
    globals()["WuWaCalc"] = w
    return True


# 不依赖 on_core_start 钩子，模块加载时主动尝试一次
reload_wuwacalc_module()
