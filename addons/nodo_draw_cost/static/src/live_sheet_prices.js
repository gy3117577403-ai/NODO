import {signal, useOnChange, usePlugin} from "@odoo/owl";
import {BusPlugin} from "@bus/services/bus_plugin";
import {useService} from "@web/core/utils/hooks";

const unitFormat = new Intl.NumberFormat("zh-CN", {minimumFractionDigits:2, maximumFractionDigits:4});
export const unitPrice = value => unitFormat.format(value);

// A price edit invalidates only the figures on screen. The CAD mesh and flat files stay cached.
export function useLiveSheetPrices(source, read, topic = "nodo.cost/sheet_prices_changed", retain = false) {
    const bus = usePlugin(BusPlugin);
    const orm = useService("orm");
    const result = signal({});
    let previous;
    useOnChange(() => [source()], key => {
        if (!key) return;
        let latest = 0;
        result.set(retain ? {...previous, loading:true} : {});
        async function refresh() {
            const sequence = ++latest;
            try {
                const value = await read(orm, key);
                if (sequence === latest) {
                    previous = {value, key};
                    result.set(previous);
                }
            } catch (error) {
                if (sequence === latest) result.set({
                    ...(retain ? previous : null), error:error.data?.message || error.message, failedKey:key,
                });
            }
        }
        const whenVisible = () => { if (!document.hidden) refresh(); };
        const unsubscribe = bus.subscribe(topic, refresh);
        window.addEventListener("focus", whenVisible);
        document.addEventListener("visibilitychange", whenVisible);
        const fallback = window.setInterval(whenVisible, 30000);
        refresh();
        return () => {
            latest++;
            unsubscribe();
            window.removeEventListener("focus", whenVisible);
            document.removeEventListener("visibilitychange", whenVisible);
            window.clearInterval(fallback);
        };
    });
    return result;
}
