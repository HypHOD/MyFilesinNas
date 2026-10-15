import { concatPathAndEncodeAll, buildShareBasePath } from "~/utils";
import useHeaderStorageList from "./useHeaderStorageList";

import useStorageConfigStore from "~/stores/storage-config";
let storageConfigStore = useStorageConfigStore();

import useRouterData from "~/composables/useRouterData";
let { fullpath, storageKey, routeRef } = useRouterData();



// 面包屑数据
let breadcrumbData = ref([]);
let initialized = false;
export default function useBreadcrumb() {

    let rootShowStorage = storageConfigStore.globalConfig.rootShowStorage;

    // 构建面包屑
    const buildBreadcrumbData = () => {
        // 1) 分享页面包屑（/share/:shareKey）
        const shareKey = routeRef.value?.params?.shareKey;
        if (shareKey) {
            const pwd = routeRef.value?.query?.pwd;
            const curPath = routeRef.value?.query?.path || '/';
            const base = buildShareBasePath(shareKey);

            const items = [];
            // 根：分享
            items.push({
                name: '分享',
                href: `${base}?${pwd ? `pwd=${encodeURIComponent(pwd)}&` : ''}path=/`,
                disable: false
            });

            if (curPath !== '/') {
                let acc = '';
                curPath.split('/').filter(Boolean).forEach((part, index, arr) => {
                    acc += '/' + part;
                    items.push({
                        name: part,
                        href: `${base}?${pwd ? `pwd=${encodeURIComponent(pwd)}&` : ''}path=${encodeURIComponent(acc)}`,
                        disable: index === arr.length - 1
                    })
                });
            }

            breadcrumbData.value = items;
        } else {
            // 2) 普通文件页面包屑
            if (!rootShowStorage && !storageKey.value) {
                breadcrumbData.value = [];
                return;
            }
            breadcrumbData.value = [
                {
                    name: storageConfigStore.globalConfig.siteHomeName || '首页',
                    href: rootPath.value,
                    disable: false
                }
            ];

            // 如果为包含根目录模式，则面包屑显示驱动器
            if (rootShowStorage) {
                let { findStorageByKey } = useHeaderStorageList();
                let storageByKey = findStorageByKey(storageKey.value);
                if (storageByKey) {
                    breadcrumbData.value.push({
                        name: storageByKey.name,
                        href: concatPathAndEncodeAll('/', storageByKey.key)
                    })
                }
            }

            if (fullpath.value) {
                fullpath.value.forEach((item, index, arr) => {
                    if (item) {
                        let breadcrumbItem = {
                            name: item,
                            href: concatPathAndEncodeAll('/', storageKey.value, arr.slice(0, index + 1).join('/')),
                            disable: index === arr.length - 1
                        }
                        breadcrumbData.value.push(breadcrumbItem);
                    }
                })
            }
        }
    };

    /**
     * 根目录路径
     */
    let rootPath = computed(() => '/' + (rootShowStorage ? '' : storageKey.value));

    if (!initialized) {
        // 普通文件页相关
        watch(() => fullpath.value, () => buildBreadcrumbData())
        watch(() => storageKey.value, () => buildBreadcrumbData())

        // 分享页相关
        watch(() => [routeRef.value?.params?.shareKey, routeRef.value?.query?.path, routeRef.value?.query?.pwd], () => buildBreadcrumbData(), { deep: true })
    }
    initialized = true;

    return {
        rootPath,
        breadcrumbData,
        buildBreadcrumbData
    }

}