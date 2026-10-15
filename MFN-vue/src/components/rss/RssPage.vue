<template>
  <div class="mx-auto w-full p-4 sm:p-6">
    <div class="bg-white rounded-lg shadow-sm">
      <nav class="flex flex-wrap items-center gap-x-6 gap-y-2 border-b border-gray-100 px-4 py-3 text-sm sm:px-6">
        <router-link v-for="item in navItems"
                     :key="item.href"
                     :to="item.href"
                     :class="item.href === route.path ? 'font-semibold text-blue-500' : 'text-gray-600 hover:text-blue-500'">
          {{ item.name }}
        </router-link>
      </nav>
      <div class="p-4 sm:p-6">
        <slot />
      </div>
    </div>
  </div>
</template>

<script setup>
const route = useRoute()

const navItems = [
  { name: '追番总览', href: '/admin/rss' },
  { name: 'RSS 订阅', href: '/admin/rss/subscriptions' },
  { name: '番剧管理', href: '/admin/rss/bangumi' },
  { name: '追番设置', href: '/admin/rss/setting' }
]
</script>
