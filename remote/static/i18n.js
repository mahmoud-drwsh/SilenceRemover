// Translations for bilingual support (EN/AR)
const TRANSLATIONS = {
  en: {
    title: 'Media Manager',
    todo: 'TODO',
    ready: 'Ready',
    all: 'All',
    trash: 'Trash',
    files: 'files',
    no_files: 'No files',
    mark_ready: 'Mark Ready',
    mark_not_ready: 'Mark as not ready',
    untitled: 'Untitled',
    edit_title: 'Edit title...',
    move_to_trash: 'Move to trash?',
    restore: 'Restore',
    delete_forever: 'Delete forever?',
    save_error: 'Error saving',
    confirm_ready: 'Mark as ready?',
    cancel: 'Cancel',
    confirm: 'Confirm',
    playing: 'Playing',
    paused: 'Paused',
    video: 'Video',
    audio: 'Audio',
    no_files: 'No files',
    more_actions: 'More actions'
  },
  ar: {
    title: 'مدير الوسائط',
    todo: 'قيد الانتظار',
    ready: 'جاهز',
    all: 'الكل',
    trash: 'المحذوفات',
    files: 'ملفات',
    no_files: 'لا توجد ملفات',
    mark_ready: 'تحديد كجاهز',
    mark_not_ready: 'تحديد كغير جاهز',
    untitled: 'بدون عنوان',
    edit_title: 'تعديل العنوان...',
    move_to_trash: 'نقل إلى المحذوفات؟',
    restore: 'استعادة',
    delete_forever: 'حذف نهائي؟',
    save_error: 'خطأ في الحفظ',
    confirm_ready: 'تحديد كجاهز؟',
    cancel: 'إلغاء',
    confirm: 'تأكيد',
    playing: 'يعمل',
    paused: 'متوقف',
    video: 'فيديو',
    audio: 'صوت',
    no_files: 'لا توجد ملفات',
    more_actions: 'المزيد'
  }
};

function getText(key, lang = window.CONFIG?.lang || 'en') {
  return TRANSLATIONS[lang]?.[key] || TRANSLATIONS['en'][key];
}
