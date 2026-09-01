<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { createSite, fetchSites, type Site } from '@/api/client'

const loading = ref(false)
const rows = ref<Site[]>([])
const dialog = ref(false)
const form = ref({ name: '', address: '' })

async function load() {
  loading.value = true
  try {
    rows.value = await fetchSites()
  } finally {
    loading.value = false
  }
}

async function submit() {
  if (!form.value.name.trim()) {
    ElMessage.warning('请填写站点名称')
    return
  }
  await createSite({ name: form.value.name.trim(), address: form.value.address || null })
  ElMessage.success('已创建')
  dialog.value = false
  form.value = { name: '', address: '' }
  await load()
}

onMounted(load)
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <el-button type="primary" @click="dialog = true">新建站点</el-button>
      <el-button @click="load" :loading="loading">刷新</el-button>
    </div>

    <el-table :data="rows" v-loading="loading" row-key="id" stripe style="width: 100%">
      <el-table-column prop="id" label="ID" width="90" />
      <el-table-column prop="name" label="名称" />
      <el-table-column prop="address" label="地址" />
      <el-table-column prop="createdAt" label="创建时间" width="200" />
    </el-table>

    <el-dialog v-model="dialog" title="新建站点" width="520px" destroy-on-close>
      <el-form label-width="88px">
        <el-form-item label="名称" required>
          <el-input v-model="form.name" placeholder="充电站名称" />
        </el-form-item>
        <el-form-item label="地址">
          <el-input v-model="form.address" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" @click="submit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.toolbar {
  margin-bottom: 12px;
  display: flex;
  gap: 8px;
}
</style>
