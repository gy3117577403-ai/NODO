import { patch } from "@web/core/utils/patch";
import { viewService } from "@web/views/view_service";

patch(viewService, {
    start(env, dependencies) {
        const { orm } = dependencies;
        const viewOrm = Object.create(orm);
        viewOrm.cache = (options) => ({
            call(model, ...args) {
                // The view contains only fields the employee can currently read.
                // A cached view can still request prices after a permission change.
                const client = model === "purchase.order" ? orm : orm.cache(options);
                return client.call(model, ...args);
            },
        });
        return super.start(env, { ...dependencies, orm: viewOrm });
    },
});
