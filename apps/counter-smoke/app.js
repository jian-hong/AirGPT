const btn=document.getElementById('action');
const root=document.getElementById('root');
btn?.addEventListener('click',()=>{
  const note=document.createElement('p');
  note.textContent='Hook this button to real app behavior (see AGENTS.md).';
  note.style.marginTop='12px';
  root?.appendChild(note);
});
// TODO: implement core UX from the user prompt
