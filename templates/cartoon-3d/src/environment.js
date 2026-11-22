export function environmentKind(text, profile) {
  const story = String(text || '').toLowerCase();
  const style = String(profile || '').toLowerCase();
  if (style === 'space' || /\b(orbit|planet|moon|spacecraft|astronaut|galaxy|asteroid|comet)\b/.test(story)) return 'space';
  if (/\b(archive|archivist|ledger|logbook|library|record|report|file|notebook|document|monitor|receiver|reading room|bookcase|bookshelf|dossier)\b/.test(story)) return 'archive';
  if (/\b(laboratory|lab|scientist|experiment|microscope|telescope)\b/.test(story)) return 'laboratory';
  if (/\b(ship|vessel|boat|ocean|sea|coast|shipwreck|sailor)\b/.test(story)) return 'harbor';
  if (/\b(forest|woods|cabin|tree|jungle|rainforest)\b/.test(story)) return 'forest';
  if (/\b(room|house|office|interior|telephone|desk|court|station)\b/.test(story)) return 'interior';
  if (style === 'mystery') return 'interior';
  return style === 'historical' ? 'old_town' : 'story_town';
}