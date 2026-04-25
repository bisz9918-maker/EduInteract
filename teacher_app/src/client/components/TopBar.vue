<template>
  <div class="topbar">
    <h1>教师备课助手</h1>
    <div class="status">{{ status }}</div>
  </div>
</template>

<script setup lang="ts">
defineProps<{ status: string }>()
</script>
