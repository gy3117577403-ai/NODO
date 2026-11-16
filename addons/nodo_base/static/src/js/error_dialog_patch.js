import { patch } from "@web/core/utils/patch";
import {
    ClientErrorDialog,
    ErrorDialog,
    NetworkErrorDialog,
    RedirectWarningDialog,
    RPCErrorDialog,
    WarningDialog,
} from "@web/core/errors/error_dialogs";

// 错误和提示弹窗的默认标题带有上游产品名，NODO 改为中性的中文标题。
// NODO 界面只提供简体中文，这里直接写中文。
const hasUpstreamName = (title) => /odoo/i.test(String(title || ""));

ErrorDialog.title = "系统错误";
ClientErrorDialog.title = "客户端错误";
NetworkErrorDialog.title = "网络错误";

const RPC_TITLES = { server: "服务器错误", script: "客户端错误", network: "网络错误" };

patch(RPCErrorDialog.prototype, {
    inferTitle() {
        super.inferTitle();
        if (hasUpstreamName(this.title)) {
            this.title = RPC_TITLES[this.props.type] || "系统错误";
        }
    },
});

patch(WarningDialog.prototype, {
    inferTitle() {
        const title = super.inferTitle();
        return hasUpstreamName(title) ? "提示" : title;
    },
});

patch(RedirectWarningDialog.prototype, {
    setup() {
        super.setup();
        if (hasUpstreamName(this.title)) {
            this.title = "提示";
        }
    },
});
