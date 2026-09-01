<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { createCamera, fetchCameras, fetchSites, updateCamera, type Camera, type Site } from '@/api/client'

const loading = ref(false)
const sites = ref<Site[]>([])
const siteId = ref<number | null>(null)
const rows = ref<Camera[]>([])

const dialog = ref(false)
const editId = ref<number | null>(null)
const form = ref({
  name: '',
  rtspUrl: '',
  channelNo: null as number | null,
  edgeBoxId: '',
})

const currentSiteId = computed(() => siteId.value)

async function loadSites() {
  sites.value = await fetchSites()
  if (!siteId.value && sites.value.length > 0) {
    siteId.value = sites.value[0]!.id
  }
}

async function loadCameras() {
  loading.value = true
  try {
    rows.value = await fetchCameras(siteId.value ?? undefined)
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editId.value = null
  form.value = { name: '', rtspUrl: '', channelNo: null, edgeBoxId: 'rk3588-01' }
  dialog.value = true
}

function openEdit(row: Camera) {
  editId.value = row.id
  form.value = {
    name: row.name,
    rtspUrl: row.rtspUrl ?? '',
    channelNo: row.channelNo,
    edgeBoxId: row.edgeBoxId ?? '',
  }
  dialog.value = true
}

async function submit() {
  if (!form.value.name.trim()) {
    ElMessage.warning('请填写相机名称')
    return
  }
  const payload = {
    name: form.value.name.trim(),
    rtspUrl: form.value.rtspUrl || null,
    channelNo: form.value.channelNo,
    edgeBoxId: form.value.edgeBoxId || null,
  }
  if (editId.value != null) {
    await updateCamera(editId.value, payload)
    ElMessage.success('已更新')
  } else {
    if (!currentSiteId.value) {
      ElMessage.warning('请先选择站点')
      return
    }
    await createCamera({ siteId: currentSiteId.value, ...payload })
    ElMessage.success('已创建')
  }
  dialog.value = false
  form.value = { name: '', rtspUrl: '', channelNo: null, edgeBoxId: '' }
  await loadCameras()
}

onMounted(async () => {
  await loadSites()
  await loadCameras()
})

watch(siteId, async () => {
  await loadCameras()
})
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <el-select v-model="siteId" placeholder="站点" style="width: 240px" filterable>
        <el-option v-for="s in sites" :key="s.id" :label="s.name" :value="s.id" />
      </el-select>

      <el-button type="primary" @click="openCreate" :disabled="!siteId">新建相机</el-button>
      <el-button @click="loadCameras" :loading="loading">刷新</el-button>
    </div>

    <el-table :data="rows" v-loading="loading" row-key="id" stripe style="width: 100%">
      <el-table-column prop="id" label="ID" width="90" />
      <el-table-column prop="name" label="名称" />
      <el-table-column prop="rtspUrl" label="RTSP" min-width="220" show-overflow-tooltip />
      <el-table-column prop="channelNo" label="通道" width="90" />
      <el-table-column prop="edgeBoxId" label="边缘盒" width="140" />
      <el-table-column prop="createdAt" label="创建时间" width="200" />
      <el-table-column label="操作" width="100" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialog" :title="editId ? '编辑相机' : '新建相机'" width="640px" destroy-on-close>
      <el-form label-width="110px">
        <el-form-item label="名称" required>
          <el-input v-model="form.name" placeholder="例如：入口球机1" />
        </el-form-item>
        <el-form-item label="RTSP URL">
          <el-input
            v-model="form.rtspUrl"
            placeholder="rtsp://admin:密码@192.168.1.111:554/Streaming/Channels/101"
          />
        </el-form-item>
        <el-form-item label="通道号">
          <el-input-number v-model="form.channelNo" :min="0" :max="32" controls-position="right" />
        </el-form-item>
        <el-form-item label="边缘盒 ID">
          <el-input v-model="form.edgeBoxId" placeholder="rk3588-01" />
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
  flex-wrap: wrap;
  align-items: center;
}
</style>
