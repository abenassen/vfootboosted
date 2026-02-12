export function SoccerField({ className }) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 396 580" className={`mx-auto aspect-396/580 max-w-full ${className}`}>
      <rect width="396" height="580" fill="url(#paint0_linear_1287_722)" rx="12"></rect>
      <mask id="mask0_1287_722" style={{ maskType: 'alpha' }} width="396" height="580" x="0" y="0" maskUnits="userSpaceOnUse">
        <rect width="396" height="580" fill="url(#paint1_linear_1287_722)" rx="12"></rect>
      </mask>
      <g mask="url(#mask0_1287_722)" className="mix-blend-overlay">
        <circle cx="198" cy="290" r="30" stroke="#000" strokeWidth="20" opacity="0.2"></circle>
        <circle cx="198" cy="290" r="70" stroke="#000" strokeWidth="20" opacity="0.2"></circle>
        <circle cx="198" cy="290" r="110" stroke="#000" strokeWidth="20" opacity="0.2"></circle>
        <circle cx="198" cy="290" r="150" stroke="#000" strokeWidth="20" opacity="0.2"></circle>
        <circle cx="198" cy="290" r="190" stroke="#000" strokeWidth="20" opacity="0.2"></circle>
        <circle cx="198" cy="290" r="230" stroke="#000" strokeWidth="20" opacity="0.2"></circle>
        <circle cx="198" cy="290" r="270" stroke="#000" strokeWidth="20" opacity="0.2"></circle>
        <circle cx="198" cy="290" r="310" stroke="#000" strokeWidth="20" opacity="0.2"></circle>
      </g>
      <path fill="#fff" d="M203 106a5 5 0 10-10.001.001A5 5 0 00203 106zM198 479a5 5 0 10-.001-10.001A5 5 0 00198 479z"></path>
      <path
        fill="#fff"
        fillRule="evenodd"
        d="M20 24a4 4 0 014-4h348a4 4 0 014 4v532a4 4 0 01-4 4H24a4 4 0 01-4-4V24zm6 263V47.356C36.648 45.03 45.031 36.648 47.356 26H84v104a4 4 0 004 4h64.957c8.991 15.543 25.796 26 45.043 26s36.052-10.457 45.043-26H308a4 4 0 004-4V26h36.644c2.325 10.648 10.708 19.031 21.356 21.356V287H263.933c-1.568-35.058-30.488-63-65.933-63-35.445 0-64.365 27.942-65.933 63H26zm344 6v239.644c-10.648 2.325-19.031 10.708-21.356 21.356H312V450a4 4 0 00-4-4h-64.957c-8.991-15.543-25.796-26-45.043-26s-36.052 10.457-45.043 26H88a4 4 0 00-4 4v104H47.356C45.03 543.352 36.648 534.969 26 532.644V293h106.067c1.568 35.058 30.488 63 65.933 63 35.445 0 64.365-27.942 65.933-63H370zm-112.074-6c-1.563-31.743-27.795-57-59.926-57s-58.363 25.257-59.926 57h53.6a7 7 0 016.326-4 7 7 0 016.326 4h53.6zm-53.6 6h53.6c-1.563 31.743-27.795 57-59.926 57s-58.363-25.257-59.926-57h53.6a7 7 0 006.326 4 7 7 0 006.326-4zM370 26v15.172A22.044 22.044 0 01354.828 26H370zM26 26h15.172A22.045 22.045 0 0126 41.172V26zm64 102V26h44v54a4 4 0 004 4h120a4 4 0 004-4V26h44v102H90zm50-50V26h116v52H140zM41.172 554H26v-15.172A22.044 22.044 0 0141.172 554zm313.656 0H370v-15.172A22.043 22.043 0 00354.828 554zM90 554h44v-54a4 4 0 014-4h120a4 4 0 014 4v54h44V452H90v102zm166 0v-52H140v52h116zm-20.047-108c-8.291-12.078-22.197-20-37.953-20-15.756 0-29.662 7.922-37.953 20h75.906zM198 154c15.756 0 29.662-7.922 37.953-20h-75.906c8.291 12.078 22.197 20 37.953 20z"
        clipRule="evenodd"
      ></path>
      <defs>
        <linearGradient id="paint0_linear_1287_722" x1="198" x2="198" y1="0" y2="580" gradientUnits="userSpaceOnUse">
          <stop stopColor="#85D034"></stop>
          <stop offset="1" stopColor="#B3EF49"></stop>
        </linearGradient>
        <linearGradient id="paint1_linear_1287_722" x1="198" x2="198" y1="0" y2="580" gradientUnits="userSpaceOnUse">
          <stop stopColor="#85D034"></stop>
          <stop offset="1" stopColor="#B3EF49"></stop>
        </linearGradient>
      </defs>
    </svg>
  );
}

function PlayerCard({ name, image, number, className = '' }) {
  return (
    <div className={`absolute z-10 w-[27cqi] pt-1 ${className}`}>
      <figure className="absolute start-0.5 top-0 flex h-[12cqi] w-[14.1cqi] justify-center overflow-hidden">
        <img src={image} alt={name} className="w-[20cqi] max-w-none shrink-0 object-cover object-top" />
      </figure>
      <div className="flex aspect-[1.6] w-[8cqi] items-center bg-team-golden-secondary ps-[0.4em] text-[2.6cqi]/none font-extrabold text-white uppercase">
        {number}
      </div>
      <div className="flex aspect-108/24 w-full items-center justify-end bg-custom-gray-900 px-2">
        <div className="w-[10cqi] truncate text-[2.6cqi]/none font-extrabold text-white uppercase">{name}</div>
      </div>
      <div className="relative h-[1cqi] bg-team-golden-primary"></div>
    </div>
  );
}

export default function TeamTactic1() {
  return (
    <div className="mx-auto w-full sm:w-[460px]">
      <div className="rounded-3xl border border-custom-gray-200 bg-white px-8 py-7 dark:border-custom-gray-600 dark:bg-custom-gray-800">
        <div className="relative -mx-8 -mt-7 px-8 py-7">
          <h3 className="pe-10 text-base/tight font-bold text-custom-gray-900 dark:text-white">Team’s Tactic V1</h3>
          <div className="absolute end-0 top-0 flex h-14 w-14 items-center justify-center rounded-se-3xl rounded-es-3xl border-s border-b border-custom-gray-200 bg-white dark:border-custom-gray-600 dark:bg-custom-gray-800">
            <svg viewBox="0 0 420 420" fill="none" xmlns="http://www.w3.org/2000/svg" className="h-7 w-7 text-team-golden-primary">
              <path
                d="M201.646 416.137C144.946 389.951 97.469 343.545 60.543 278.221C30.33 224.771 13.58 169.737 4.849 132.979L0 112.558L20.478 108.517C29.676 106.701 36.353 98.519 36.353 89.064C36.353 87.535 36.171 85.986 35.811 84.46L31.579 64.862L68.813 56.045V18.129L83.947 14.518C125.355 4.884 167.706 0 210.202 0C252.699 0 294.762 4.884 336.17 14.518L351.208 18.129V56.045L388.444 64.862L384.015 84.461C383.657 85.986 383.572 87.538 383.572 89.064C383.572 98.519 390.297 106.701 399.497 108.517L420 112.558L415.161 132.981C406.428 169.739 389.684 224.774 359.473 278.221C322.549 343.545 275.075 389.95 218.367 416.141L210.01 420L201.646 416.137Z"
                fill="currentColor"
              />
              <path
                d="M210 26C249.08 26 288.199 30.49 326.273 39.344L330.666 40.365V44.899V76.042L357.217 82.392L362.729 83.71L361.421 89.253C360.846 91.694 360.555 94.187 360.555 96.66C360.555 111.915 371.342 125.116 386.206 128.049L392 129.194L390.628 134.969C382.592 168.782 367.193 219.379 339.47 268.405C306.042 327.514 263.28 369.405 212.366 392.909L210.001 394L207.635 392.908C156.723 369.404 113.959 327.513 80.531 268.404C52.807 219.379 37.408 168.782 29.373 134.968L28 129.193L33.795 128.048C48.658 125.115 59.446 111.914 59.446 96.659C59.446 94.185 59.154 91.692 58.579 89.252L57.272 83.709L62.784 82.391L89.335 76.041V44.898V40.365L93.727 39.344C131.802 30.49 170.921 26 210 26Z"
                className="fill-custom-gray-900"
              />
              <path
                d="M210 34C247.854 34 285.747 38.279 322.666 46.722V76.042V82.355L328.806 83.823L353.174 89.651C352.763 91.972 352.555 94.321 352.555 96.661C352.555 114.914 364.931 130.818 382.308 135.36C374.25 168.639 359.165 217.325 332.506 264.466C300.136 321.705 258.926 362.315 210.001 385.186C161.075 362.314 119.865 321.706 87.496 264.466C60.837 217.324 45.752 168.638 37.695 135.359C55.073 130.817 67.447 114.914 67.447 96.66C67.447 94.322 67.239 91.973 66.827 89.65L91.196 83.822L97.335 82.354V76.041V46.721C134.252 38.28 172.149 34 210 34ZM210 26C170.921 26 131.801 30.49 93.728 39.344L89.336 40.365V44.898V76.042L62.785 82.392L57.273 83.71L58.58 89.253C59.155 91.693 59.447 94.187 59.447 96.66C59.447 111.915 48.659 125.116 33.796 128.049L28 129.193L29.374 134.968C37.409 168.781 52.808 219.378 80.532 268.404C113.96 327.513 156.723 369.404 207.636 392.908L210.002 394L212.367 392.908C263.28 369.404 306.043 327.513 339.471 268.404C367.195 219.379 382.593 168.782 390.629 134.968L392.001 129.193L386.207 128.048C371.343 125.115 360.556 111.914 360.556 96.659C360.556 94.185 360.847 91.693 361.422 89.252L362.73 83.709L357.218 82.391L330.667 76.041V44.899V40.365L326.274 39.344C288.199 30.49 249.08 26 210 26Z"
                className="fill-white"
              />
              <path
                fillRule="evenodd"
                clipRule="evenodd"
                d="M210.044 114C210.044 114 254.447 142.648 304.491 145.051C304.491 145.051 309.988 171.923 307.221 198.278C307.221 198.278 290.07 198.51 271.19 193.843C271.19 193.843 272.964 183.446 272.282 177.209C272.282 177.209 233.793 170.418 210.044 156.694C210.044 156.694 176.743 171.387 148.354 177.209C148.354 177.209 147.671 197.724 152.175 213.249C152.175 213.249 187.661 208.121 210.044 197.17C210.044 197.17 251.399 215.883 305.038 217.131C305.038 217.131 282.199 303.81 210.044 338.001C210.044 338.001 163.094 319.519 135.797 272.021C135.797 272.021 156.36 271.283 175.732 266.654C176.721 268.349 192.58 281.955 210.044 293.092C210.044 293.092 238.889 281.727 255.903 247.625C255.903 247.625 227.878 244.113 210.044 236.537C210.044 236.537 169.281 250.767 127.061 252.617C127.061 252.617 103.859 207.151 115.051 144.498C115.051 144.498 168.007 144.497 210.044 114Z"
                fill="currentColor"
              />
              <path
                d="M218.323 65.462L210.24 49L202.157 65.462L184.081 68.102L197.16 80.916L194.073 99.009L210.24 90.467L226.406 99.009L223.319 80.916L236.398 68.102L218.323 65.462ZM148.835 90.709L142.5 77.807L136.165 90.709L122 92.777L132.25 102.819L129.831 117L142.5 110.305L155.17 117L152.75 102.82L163 92.777L148.835 90.709ZM298 92.777L283.835 90.709L277.5 77.807L271.165 90.709L256.999 92.777L267.25 102.819L264.83 117L277.5 110.305L290.17 117L287.75 102.82L298 92.777Z"
                className="fill-white"
              />
            </svg>
          </div>
        </div>

        <div className="-mx-8 overflow-hidden rounded-t-3xl">
          <div className="bg-custom-gray-900 px-8 pt-4 pb-10 dark:bg-white">
            <h4 className="text-xs/tight font-bold text-white uppercase dark:text-custom-gray-900">Formation: 4 - 3 - 3</h4>
          </div>

          <div className="-my-6 rounded-t-3xl bg-white p-8 dark:bg-custom-gray-800">
            <div className="@container relative isolate">
              <PlayerCard
                name={`Rdgrs`}
                image={`https://danfisher-bucket-1.s3.us-east-2.amazonaws.com/sportyblocks/player-7.png`}
                number={`01`}
                className={`start-[35.2%] bottom-[6.2%]`}
              />
              <PlayerCard
                name={`Drake`}
                image={`https://danfisher-bucket-1.s3.us-east-2.amazonaws.com/sportyblocks/player-placeholder.png`}
                number={`03`}
                className={`start-[2.3%] bottom-[12.9%]`}
              />
              <PlayerCard
                name={`Stvns`}
                image={`https://danfisher-bucket-1.s3.us-east-2.amazonaws.com/sportyblocks/player-10.png`}
                number={`18`}
                className={`start-[68.9%] bottom-[12.2%]`}
              />
              <PlayerCard
                name={`Smrs`}
                image={`https://danfisher-bucket-1.s3.us-east-2.amazonaws.com/sportyblocks/player-placeholder.png`}
                number={`06`}
                className={`start-[17.4%] bottom-[24.8%]`}
              />
              <PlayerCard
                name={`Stark`}
                image={`https://danfisher-bucket-1.s3.us-east-2.amazonaws.com/sportyblocks/player-11.png`}
                number={`05`}
                className={`start-[57.8%] bottom-[24.1%]`}
              />
              <PlayerCard
                name={`McCoy`}
                image={`https://danfisher-bucket-1.s3.us-east-2.amazonaws.com/sportyblocks/player-12.png`}
                number={`07`}
                className={`start-[35.1%] bottom-[38.6%]`}
              />
              <PlayerCard
                name={`West`}
                image={`https://danfisher-bucket-1.s3.us-east-2.amazonaws.com/sportyblocks/player-13.png`}
                number={`12`}
                className={`start-[3.8%] bottom-[47.6%]`}
              />
              <PlayerCard
                name={`Bishop`}
                image={`https://danfisher-bucket-1.s3.us-east-2.amazonaws.com/sportyblocks/player-placeholder.png`}
                number={`11`}
                className={`start-[68.9%] bottom-[47.6%]`}
              />
              <PlayerCard
                name={`Hwltt`}
                image={`https://danfisher-bucket-1.s3.us-east-2.amazonaws.com/sportyblocks/player-placeholder.png`}
                number={`08`}
                className={`start-[35.1%] top-[28.1%]`}
              />
              <PlayerCard
                name={`Sprty`}
                image={`https://danfisher-bucket-1.s3.us-east-2.amazonaws.com/sportyblocks/player-1.png`}
                number={`09`}
                className={`start-[9.6%] top-[15.3%]`}
              />
              <PlayerCard
                name={`LBeau`}
                image={`https://danfisher-bucket-1.s3.us-east-2.amazonaws.com/sportyblocks/player-3.png`}
                number={`37`}
                className={`start-[63.1%] top-[15.3%]`}
              />
              <SoccerField className={`-z-10`} />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
