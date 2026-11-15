/* Presentation shell only: existing forms, IDs and pipeline handlers stay in place. */
(()=>{
  const main=document.querySelector('main'),grid=document.querySelector('.grid');
  const playerPanel=grid.querySelector('section>.panel:nth-child(1)'),slotsPanel=grid.querySelector('section>.panel:nth-child(2)'),logsPanel=grid.querySelector('section>.panel:nth-child(3)');
  const panels=[...grid.querySelector('aside').children],example=document.querySelector('.example-strip'),flow=document.querySelector('.flowstrip');
  const shell=document.createElement('div');shell.className='studio-shell';
  const rail=document.createElement('aside');rail.className='studio-rail';
  rail.innerHTML='<a class="rail-brand" href="/studio"><span class="rail-mark">ıı</span> intervals<span class="brand-period">.</span></a><div class="rail-kicker">CREATOR WORKSPACE</div><nav aria-label="Studio navigation"><button class="studio-nav active" data-view="overview"><span>◉</span> Overview</button><button class="studio-nav" data-view="episodes"><span>▤</span> Episodes</button><button class="studio-nav" data-view="campaigns"><span>▥</span> Campaigns</button><button class="studio-nav" data-view="voices"><span>◌</span> Voice library</button></nav><div class="rail-note"><span class="live-dot"></span><div>Local studio<small>Your stories, behind the scenes</small></div></div>';
  main.before(shell);shell.append(rail,main);
  main.querySelector('header').innerHTML='<div class="studio-breadcrumb">Workspace <span>/</span> <b id="studioViewLabel">Overview</b></div><a class="listener-link" href="/" target="_blank">Open listener experience <span>↗</span></a>';
  const heading=main.querySelector('h1'),lead=main.querySelector('.lead'),hero=document.createElement('section');hero.className='studio-hero';
  hero.innerHTML='<div class="studio-hero-copy"><span class="studio-eyebrow"><i></i> THE OTHER SIDE OF PLAY</span><h1>Make the break<br><em>part of the story.</em></h1><p>Thoughtful placements. A voice that fits.<br>One uninterrupted listening experience.</p><button class="hero-action" data-go="campaigns">Build an edition <span>↗</span></button></div><div class="studio-hero-art" aria-hidden="true"><div class="art-ring ring-one"></div><div class="art-ring ring-two"></div><div class="art-disc"><div class="disc-center">the art of<br><em>fitting in.</em></div></div><div class="art-orange"></div><span>CONTEXT IS EVERYTHING.</span></div>';
  heading.replaceWith(hero);lead.remove();
  const views=document.createElement('div');views.className='studio-views';
  for(const name of ['overview','episodes','campaigns','voices']){const view=document.createElement('section');view.id='view-'+name;view.className='studio-view';view.hidden=name!=='overview';views.append(view)}
  grid.before(views);
  const overview=views.querySelector('#view-overview');
  overview.append(flow);
  const overviewHeading=document.createElement('div');overviewHeading.className='workspace-heading';overviewHeading.innerHTML='<div><span class="studio-eyebrow">THE EDITOR’S DESK</span><h2>Your listening experience, considered.</h2></div><span class="quiet-label">Made backstage. Heard naturally.</span>';overview.append(overviewHeading);
  const board=document.createElement('div');board.className='overview-board';
  const stage=document.createElement('div');stage.className='stage-column';
  example.open=true;example.classList.add('demo-feature');stage.append(example,playerPanel,slotsPanel);
  const notes=document.createElement('aside');notes.className='notes-column';
  notes.innerHTML='<section class="editor-note"><span class="studio-eyebrow">YOUR CURRENT EPISODE</span><div class="note-art" aria-hidden="true"><span>Make room<br>for a new<br><em>perspective.</em></span></div><h3 id="studioEpisodeName">Loading your episode…</h3><p id="studioEpisodeStatus">Your source audio and analysis stay in the workspace.</p><button class="text-action" data-go="episodes">Manage episodes <span>↗</span></button></section><section class="editor-note paper-note"><span class="studio-eyebrow">A SIMPLE WAY TO DEMO</span><h3>Set the scene.<br>Then press play.</h3><ol><li>Choose the episode and advertiser mix</li><li>Review the fit and listen to the read</li><li>Publish the finished listener edition</li></ol><button class="text-action" data-go="campaigns">Open campaign setup <span>↗</span></button></section>';
  const diagnostics=document.createElement('details');diagnostics.className='diagnostics';diagnostics.innerHTML='<summary>Activity & diagnostics</summary>';diagnostics.append(logsPanel);notes.append(diagnostics);board.append(stage,notes);overview.append(board);
  const introductions={episodes:['YOUR SOURCE MATERIAL','Every good edition starts here.','Add a podcast once, then reuse its analysis across audiences and campaigns.'],campaigns:['THE RIGHT FIT','Build around the conversation.','Choose your audience and businesses, then let the slot teams compare, write, and review.'],voices:['THE HUMAN ELEMENT','Find the voice of your story.','Keep brand and host voices in one place, with clear permission for every use.']};
  for(const [name,copy] of Object.entries(introductions)){const intro=document.createElement('div');intro.className='view-intro';intro.innerHTML='<span class="studio-eyebrow">'+copy[0]+'</span><h2>'+copy[1]+'</h2><p>'+copy[2]+'</p>';views.querySelector('#view-'+name).append(intro)}
  panels[0].classList.add('episode-settings');views.querySelector('#view-episodes').append(panels[0]);
  panels[1].classList.add('campaign-settings');views.querySelector('#view-campaigns').append(panels[1]);
  panels[2].classList.add('voice-settings');views.querySelector('#view-voices').append(panels[2]);
  panels[3]?.remove();grid.remove();
  const filter=document.createElement('input');filter.id='advertiserSearch';filter.type='search';filter.placeholder='Find a business, product, or category…';filter.setAttribute('aria-label','Search advertiser inventory');document.getElementById('inventory').before(filter);
  filter.addEventListener('input',()=>{const term=filter.value.toLowerCase();document.querySelectorAll('#inventory .ad').forEach(row=>row.hidden=!row.textContent.toLowerCase().includes(term))});
  const map={overview:'Overview',episodes:'Episodes',campaigns:'Campaigns',voices:'Voice library'};
  function show(name){document.querySelectorAll('.studio-view').forEach(view=>view.hidden=view.id!=='view-'+name);document.querySelectorAll('.studio-nav').forEach(button=>{button.classList.toggle('active',button.dataset.view===name);if(button.dataset.view===name)button.setAttribute('aria-current','page');else button.removeAttribute('aria-current')});hero.hidden=name!=='overview';document.getElementById('studioViewLabel').textContent=map[name];window.scrollTo({top:0,behavior:'smooth'})}
  document.querySelectorAll('[data-view],[data-go]').forEach(button=>button.addEventListener('click',()=>show(button.dataset.view||button.dataset.go)));
  document.querySelector('.studio-nav').setAttribute('aria-current','page');
  document.getElementById('prepare').addEventListener('click',()=>{setTimeout(()=>{if(typeof session!=='undefined'&&session){show('overview');slotsPanel.scrollIntoView({behavior:'smooth',block:'center'})}},400)});
})();
