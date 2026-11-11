import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from '@/App.vue'
import router from '@/Router'
import '@/Styles/Main.css'

createApp(App).use(createPinia()).use(router).mount('#app')
